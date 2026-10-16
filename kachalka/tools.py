"""yt-dlp, ffmpeg и deno: где их взять.

Сначала ищем свою копию в папке данных, потом то, что уже стоит в системе
(Homebrew, winget, apt). Чего нет, скачиваем с официальных страниц проектов
и сверяем контрольные суммы там, где проекты их публикуют.
"""
from __future__ import annotations

import fnmatch
import hashlib
import logging
import os
import platform
import re
import shutil
import subprocess
import tarfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from . import REPO, __version__, system
from .ytdlp import version_age_days

log = logging.getLogger(__name__)

USER_AGENT = f"Kachalka/{__version__} (+https://github.com/{REPO})"
YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/"
DENO_URL = "https://github.com/denoland/deno/releases/latest/download/"
FFBUILDS_URL = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/"
# Для macOS у yt-dlp нет своих сборок ffmpeg: берём статические у Martin Riedl.
RIEDL_URL = "https://ffmpeg.martin-riedl.de/redirect/latest/macos/{arch}/{channel}/{name}.zip"
AUTO_UPDATE_DAYS = 7
CA_BUNDLES = ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt")

TOOL_INFO = {
    "yt-dlp": "Скачивает видео с сайтов",
    "ffmpeg": "Склеивает видео со звуком и меняет форматы",
    "deno": "Нужен YouTube, без него часть видео не скачать",
}
REQUIRED = ("yt-dlp", "ffmpeg")


class ToolError(Exception):
    pass


@dataclass
class Package:
    urls: list[str]           # зеркала по порядку
    files: dict[str, str]     # имя или маска в архиве -> имя у нас ("" значит то же самое)
    kind: str = "raw"         # raw, zip или tar
    sums: str | None = None   # файл с контрольными суммами


def _arm() -> bool:
    return platform.machine().lower() in ("arm64", "aarch64")


def packages(name: str) -> list[Package]:
    exe = ".exe" if system.IS_WIN else ""
    if name == "yt-dlp":
        if system.IS_WIN:
            asset = "yt-dlp.exe"
        elif system.IS_MAC:
            asset = "yt-dlp_macos"
        else:
            asset = "yt-dlp_linux_aarch64" if _arm() else "yt-dlp_linux"
        return [Package([YTDLP_URL + asset], {asset: "yt-dlp" + exe}, "raw", YTDLP_URL + "SHA2-256SUMS")]
    if name == "deno":
        if system.IS_WIN:
            target = "x86_64-pc-windows-msvc"
        else:
            target = ("aarch64" if _arm() else "x86_64") + ("-apple-darwin" if system.IS_MAC else "-unknown-linux-gnu")
        asset = f"deno-{target}.zip"
        return [Package([DENO_URL + asset], {"deno" + exe: ""}, "zip", DENO_URL + asset + ".sha256sum")]
    if name == "ffmpeg":
        if system.IS_WIN:
            asset = "ffmpeg-master-latest-win64-gpl-shared.zip"
            files = {"ffmpeg.exe": "", "ffprobe.exe": "", "*.dll": ""}
            return [Package([FFBUILDS_URL + asset], files, "zip", FFBUILDS_URL + "checksums.sha256")]
        if system.IS_MAC:
            arch = "arm64" if _arm() else "amd64"
            return [
                Package([RIEDL_URL.format(arch=arch, channel=channel, name=tool) for channel in ("release", "snapshot")],
                        {tool: ""}, "zip")
                for tool in ("ffmpeg", "ffprobe")
            ]
        asset = f"ffmpeg-master-latest-{'linuxarm64' if _arm() else 'linux64'}-gpl.tar.xz"
        return [Package([FFBUILDS_URL + asset], {"ffmpeg": "", "ffprobe": ""}, "tar", FFBUILDS_URL + "checksums.sha256")]
    raise ValueError(name)


def _open(url: str, timeout: float = 60):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout)


def _expected_sha(pkg: Package, asset: str) -> str | None:
    if not pkg.sums:
        return None
    with _open(pkg.sums, 30) as r:
        text = r.read().decode("utf-8", "replace")
    if pkg.sums.endswith(".sha256sum"):
        # У deno в файле одна сумма, а в сборке для Windows ещё и в формате PowerShell.
        m = re.search(r"\b[0-9a-fA-F]{64}\b", text)
        if m:
            return m.group(0).lower()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == asset and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0].lower()
    raise ToolError(f"Не нашёл контрольную сумму для {asset}.")


def _download(url: str, dest: Path, on_progress) -> str:
    digest = hashlib.sha256()
    with _open(url) as r, open(dest, "wb") as out:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        on_progress(0, total)
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            on_progress(done, total)
    return digest.hexdigest()


def _extract(pkg: Package, archive: Path, out_dir: Path):
    def target(member: str) -> str | None:
        base = PurePosixPath(member.replace("\\", "/")).name
        for pattern, rename in pkg.files.items():
            if fnmatch.fnmatch(base, pattern):
                return rename or base
        return None

    written: list[Path] = []
    if pkg.kind == "raw":
        dest = out_dir / next(iter(pkg.files.values()))
        shutil.copyfile(archive, dest)
        written.append(dest)
    elif pkg.kind == "zip":
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                name = target(info.filename)
                if name and not info.is_dir():
                    with zf.open(info) as src, open(out_dir / name, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    written.append(out_dir / name)
    else:
        with tarfile.open(archive, "r:*") as tf:
            for member in tf.getmembers():
                name = target(member.name)
                src = tf.extractfile(member) if name and member.isfile() else None
                if src:
                    with src, open(out_dir / name, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    written.append(out_dir / name)
    names = {p.name for p in written}
    for pattern, rename in pkg.files.items():
        if "*" not in pattern and (rename or pattern) not in names:
            raise ToolError(f"В скачанном архиве нет {rename or pattern}.")
    for path in written:
        path.chmod(0o755)


class Tools:
    def __init__(self, paths: system.Paths, use_system: bool = True):
        self.paths = paths
        self.use_system = use_system and not os.environ.get("KACHALKA_OWN_TOOLS")
        self.lock = threading.Lock()
        self.state = {name: {"status": "checking", "source": "", "path": "", "done": 0, "total": 0,
                             "step": 0, "steps": 0, "error": ""} for name in TOOL_INFO}
        self.installing = False
        self.version = ""
        self.update = {"running": False, "ok": None, "log": "", "auto": False}
        # Версию yt-dlp узнаём уже в фоне: его сборка для macOS стартует несколько секунд.
        self.refresh(check_version=False)

    # -- поиск
    @staticmethod
    def exe(name: str) -> str:
        return name + (".exe" if system.IS_WIN else "")

    def _find(self, name: str) -> tuple[str, str]:
        own = self.paths.bin / self.exe(name)
        if own.is_file():
            return str(own), "own"
        if self.use_system:
            found = shutil.which(name, path=system.SEARCH_PATH)
            if found:
                return found, "system"
        return "", ""

    def refresh(self, check_version: bool = True):
        for name in TOOL_INFO:
            path, source = self._find(name)
            if name == "ffmpeg" and path:
                probe = Path(path).with_name(self.exe("ffprobe"))
                if not probe.exists() and not shutil.which("ffprobe", path=system.SEARCH_PATH):
                    path, source = "", ""
            with self.lock:
                st = self.state[name]
                if path:
                    st.update(status="ready", path=path, source=source, error="")
                elif st["status"] not in ("downloading", "error"):
                    st.update(status="missing", path="", source="")
        if check_version:
            self.version = self._ytdlp_version()

    def _ytdlp_version(self) -> str:
        if not self.ytdlp:
            return ""
        try:
            return system.run([self.ytdlp, "--version"], timeout=60, env=self.env()).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    @property
    def ytdlp(self) -> str:
        return self.state["yt-dlp"]["path"]

    @property
    def ready(self) -> bool:
        return all(self.state[name]["status"] == "ready" for name in REQUIRED)

    def ytdlp_args(self) -> list[str]:
        ffmpeg = self.state["ffmpeg"]["path"]
        return ["--ffmpeg-location", str(Path(ffmpeg).parent)] if ffmpeg else []

    def env(self) -> dict:
        env = dict(os.environ)
        dirs = [str(self.paths.bin)] + [str(Path(st["path"]).parent) for st in self.state.values() if st["path"]]
        env["PATH"] = os.pathsep.join(dict.fromkeys(dirs + [system.SEARCH_PATH]))
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        # Статический ffmpeg ищет сертификаты по пути со своей сборочной машины и без
        # подсказки не открывает https. Даём ему системный набор (в Windows не нужно).
        if not system.IS_WIN and "SSL_CERT_FILE" not in env:
            for bundle in CA_BUNDLES:
                if os.path.isfile(bundle):
                    env["SSL_CERT_FILE"] = bundle
                    break
        return env

    def snapshot(self) -> dict:
        with self.lock:
            items = [{"name": name, "about": TOOL_INFO[name], **dict(st)} for name, st in self.state.items()]
        return {"ready": self.ready, "installing": self.installing, "items": items, "version": self.version,
                "version_age": version_age_days(self.version), "update": dict(self.update)}

    # -- установка
    def ensure_async(self):
        with self.lock:
            if self.installing:
                return
            self.installing = True
        threading.Thread(target=self._ensure, name="tools", daemon=True).start()

    def _ensure(self):
        try:
            for name in TOOL_INFO:
                if self.state[name]["status"] != "ready":
                    self._install(name)
            self.refresh()
            # YouTube часто ломает загрузчики, поэтому свою копию yt-dlp держим свежей,
            # но проверяем обновление не чаще раза в сутки.
            stamp = self.paths.bin / ".update-check"
            age = version_age_days(self.version)
            fresh_check = stamp.exists() and time.time() - stamp.stat().st_mtime < 24 * 3600
            if self.state["yt-dlp"]["source"] == "own" and age is not None and age > AUTO_UPDATE_DAYS and not fresh_check:
                stamp.touch()
                self.update_ytdlp(auto=True)
        finally:
            with self.lock:
                self.installing = False

    def _install(self, name: str):
        st = self.state[name]
        pkgs = packages(name)
        staging = self.paths.bin / f".new-{name}"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        with self.lock:
            st.update(status="downloading", done=0, total=0, step=0, steps=len(pkgs), error="")
        try:
            for step, pkg in enumerate(pkgs, 1):
                st["step"] = step
                archive = staging / "download.part"

                def progress(done, total):
                    st["done"], st["total"] = done, total

                errors = []
                for url in pkg.urls:
                    try:
                        digest = _download(url, archive, progress)
                        break
                    except (urllib.error.URLError, OSError) as e:
                        errors.append(f"{url}: {e}")
                else:
                    log.warning("download failed: %s", errors)
                    raise ToolError("Не получилось скачать. Проверь интернет и нажми «Повторить».")
                expected = _expected_sha(pkg, PurePosixPath(urlparse(url).path).name)
                if expected and expected != digest:
                    raise ToolError("Скачанный файл не совпал с контрольной суммой. Нажми «Повторить».")
                _extract(pkg, archive, staging)
                archive.unlink()
            for item in staging.iterdir():
                os.replace(item, self.paths.bin / item.name)
            if system.IS_MAC:
                for item in self.paths.bin.iterdir():
                    system.run(["xattr", "-d", "com.apple.quarantine", str(item)], timeout=10)
            self._verify(name)
            with self.lock:
                st.update(status="ready", path=str(self.paths.bin / self.exe(name)), source="own", error="")
            log.info("installed %s", name)
        except Exception as e:  # noqa: BLE001 - любую ошибку показываем в окне
            log.exception("install %s failed", name)
            message = str(e) if isinstance(e, ToolError) else f"Не получилось установить: {e}"
            with self.lock:
                st.update(status="error", error=message)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _verify(self, name: str):
        flag = "-version" if name == "ffmpeg" else "--version"
        try:
            p = system.run([str(self.paths.bin / self.exe(name)), flag], timeout=120, env=self.env())
        except (OSError, subprocess.SubprocessError) as e:
            raise ToolError(f"Скачанная программа не запускается: {e}") from e
        if p.returncode != 0:
            raise ToolError("Скачанная программа не запускается: " + (p.stderr or p.stdout).strip()[-200:])

    # -- обновление yt-dlp
    def update_command(self) -> list[str]:
        st = self.state["yt-dlp"]
        path = st["path"]
        if st["source"] == "own":
            return [path, "-U"]
        real = os.path.realpath(path)
        if "/Cellar/" in real or real.startswith(("/opt/homebrew", "/usr/local/Homebrew")):
            return ["brew", "upgrade", "yt-dlp"]
        if "pipx" in real:
            return ["pipx", "upgrade", "yt-dlp"]
        if "WinGet" in real:
            return ["winget", "upgrade", "--id", "yt-dlp.yt-dlp", "--silent", "--accept-source-agreements"]
        return [path, "-U"]

    def update_ytdlp(self, auto: bool = False):
        up = self.update
        if up["running"] or not self.ytdlp:
            return
        up.update(running=True, ok=None, log="", auto=auto)
        try:
            p = system.run(self.update_command(), timeout=900, env=self.env())
            up["log"] = ((p.stdout or "") + (p.stderr or "")).strip()[-2000:]
            up["ok"] = p.returncode == 0
        except (OSError, subprocess.SubprocessError) as e:
            up["log"], up["ok"] = str(e), False
        self.version = self._ytdlp_version()
        up["running"] = False
        log.info("yt-dlp update ok=%s version=%s", up["ok"], self.version)
