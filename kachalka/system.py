"""Всё, что зависит от операционной системы: папки, файлы, буфер обмена, процессы."""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import uuid
from pathlib import Path

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
PLATFORM = "win" if IS_WIN else "mac" if IS_MAC else "linux"

# Приложение, запущенное из Finder или меню «Пуск», видит урезанный PATH.
_extra = []
if IS_MAC:
    _extra = ["/opt/homebrew/bin", "/usr/local/bin"]
elif IS_WIN and os.environ.get("LOCALAPPDATA"):
    _extra = [os.path.join(os.environ["LOCALAPPDATA"], "Microsoft", "WinGet", "Links")]
SEARCH_PATH = os.pathsep.join(_extra + [os.environ.get("PATH", "")])


class Paths:
    """Где Качалка хранит настройки, историю, свои программы и недокачанные куски."""

    def __init__(self, root: str | os.PathLike | None = None):
        self.root = Path(root).expanduser() if root else default_data_dir()
        custom = root is not None or bool(os.environ.get("KACHALKA_DATA"))
        self.settings = self.root / "settings.json"
        self.jobs = self.root / "jobs.json"
        self.tmp = self.root / "tmp"
        self.bin = self.root / "bin"
        self.log = log_file(self.root, custom)

    def ensure(self):
        for folder in (self.root, self.tmp, self.bin, self.log.parent):
            folder.mkdir(parents=True, exist_ok=True)


def default_data_dir() -> Path:
    if os.environ.get("KACHALKA_DATA"):
        return Path(os.environ["KACHALKA_DATA"]).expanduser()
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / "Kachalka"
    if IS_WIN:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Kachalka"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "kachalka"


def log_file(root: Path, custom: bool = False) -> Path:
    # Обычный запуск на Mac пишет лог туда, где его ищет «Консоль», а тестовый пишет в свою папку.
    if IS_MAC and not custom:
        return Path.home() / "Library" / "Logs" / "Kachalka.log"
    return root / "kachalka.log"


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- папки

def _windows_known_folder(guid: str) -> str | None:
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    u = uuid.UUID(guid)
    g = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8).from_buffer_copy(u.bytes[8:]))
    out = ctypes.c_wchar_p()
    if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) != 0:
        return None
    try:
        return out.value
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


def downloads_dir() -> Path:
    """Системная папка «Загрузки»: в Windows её часто переносят на другой диск."""
    if IS_WIN:
        try:
            found = _windows_known_folder("374DE290-123F-4565-9164-39C4925E467B")
            if found:
                return Path(found)
        except (OSError, AttributeError, ValueError):
            pass
    elif not IS_MAC and shutil.which("xdg-user-dir"):
        try:
            found = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, timeout=5).stdout.strip()
            if found and found != str(Path.home()):
                return Path(found)
        except (OSError, subprocess.SubprocessError):
            pass
    return Path.home() / "Downloads"


# ---------------------------------------------------------------- процессы

def popen_flags() -> dict:
    """Дочерние процессы: без чёрного окна консоли в Windows, своей группой везде."""
    if IS_WIN:
        return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def run(cmd, **kw) -> subprocess.CompletedProcess:
    kw.setdefault("stdin", subprocess.DEVNULL)
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("encoding", "utf-8")
    kw.setdefault("errors", "replace")
    if IS_WIN:
        kw.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
    return subprocess.run(cmd, **kw)


def kill_tree(proc: subprocess.Popen):
    """Останавливает yt-dlp вместе с ffmpeg, который он успел запустить."""
    if proc.poll() is not None:
        return
    if IS_WIN:
        run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], timeout=15)
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


# ---------------------------------------------------------------- файлы

def _spawn(cmd):
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     **({"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WIN else {}))


def open_path(path: str):
    if IS_WIN:
        os.startfile(path)  # noqa: S606 - так Windows открывает файл программой по умолчанию
    elif IS_MAC:
        _spawn(["open", path])
    else:
        _spawn(["xdg-open", path])


def reveal(path: str):
    """Показывает файл в Finder или Проводнике, выделив его."""
    if IS_WIN:
        subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
    elif IS_MAC:
        _spawn(["open", "-R", path])
    else:
        open_path(os.path.dirname(path))


def clipboard_text() -> str:
    try:
        if IS_MAC:
            return run(["pbpaste"], timeout=5).stdout
        if IS_WIN:
            return _windows_clipboard()
        for cmd in (["wl-paste", "--no-newline"], ["xclip", "-selection", "clipboard", "-o"], ["xsel", "-b", "-o"]):
            if shutil.which(cmd[0]):
                return run(cmd, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def _windows_clipboard() -> str:
    import ctypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    if not user32.OpenClipboard(None):
        return ""
    try:
        handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return ""
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def pick_folder_fallback(current: str) -> str | None:
    """Выбор папки без окна pywebview, например когда интерфейс открыт в браузере."""
    prompt = "Куда сохранять загрузки?"
    if IS_MAC:
        where = f' default location (POSIX file "{current}")' if os.path.isdir(current) else ""
        out = run(["osascript", "-e", f'POSIX path of (choose folder with prompt "{prompt}"{where})'], timeout=600)
        return out.stdout.strip().rstrip("/") or None
    if IS_WIN:
        script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
            f"$d.Description = '{prompt}'; $d.SelectedPath = $env:KACHALKA_CURRENT;"
            "if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }"
        )
        env = dict(os.environ, KACHALKA_CURRENT=current)
        out = run(["powershell", "-NoProfile", "-STA", "-Command", script], timeout=600, env=env)
        return out.stdout.strip() or None
    if shutil.which("zenity"):
        out = run(["zenity", "--file-selection", "--directory", f"--title={prompt}", f"--filename={current}/"], timeout=600)
        return out.stdout.strip() or None
    return None


def is_dark() -> bool:
    """Тёмная ли тема в системе: чтобы окно не вспыхивало белым до загрузки страницы."""
    try:
        if IS_MAC:
            return run(["defaults", "read", "-g", "AppleInterfaceStyle"], timeout=3).stdout.strip() == "Dark"
        if IS_WIN:
            import winreg

            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except (OSError, subprocess.SubprocessError):
        pass
    return False
