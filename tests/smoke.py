"""Сквозная проверка без окна: сервер, установка компонентов, превью, загрузка видео и звука.

    python tests/smoke.py              # yt-dlp и ffmpeg берутся из системы, если есть
    python tests/smoke.py --own-tools  # как у нового пользователя: всё скачивается заново

Ролики: Big Buck Bunny, (c) Blender Foundation, CC BY 3.0. Короткий клип без звука
и пятисекундный кусок полной версии с archive.org.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

CLIP = "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360/Big_Buck_Bunny_360_10s_1MB.mp4"
FULL = "https://archive.org/details/BigBuckBunny_124"
ROOT = Path(__file__).resolve().parent.parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # консоль Windows на CI не в UTF-8
local = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(base: str, path: str, body: dict | None = None) -> dict:  # noqa: D103
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, headers={"X-Kachalka": "1", "Content-Type": "application/json"})
    try:
        with local.open(req, timeout=300) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{path}: {e.code} {e.read().decode('utf-8', 'replace')}") from e


def wait(what: str, check, timeout: float, every: float = 2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = check()
        if result:
            return result
        time.sleep(every)
    raise SystemExit(f"не дождался: {what}")


def main() -> int:
    # KACHALKA_SMOKE_DATA позволяет не скачивать компоненты заново при повторных прогонах.
    data_dir = Path(os.environ.get("KACHALKA_SMOKE_DATA") or tempfile.mkdtemp(prefix="kachalka-smoke-"))
    out_dir = data_dir / "out"
    cmd = [sys.executable, "-m", "kachalka", "--headless", "--port", "0", "--data-dir", str(data_dir)]
    if "--own-tools" in sys.argv:
        cmd.append("--own-tools")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, text=True, encoding="utf-8", env=env)
    try:
        base = proc.stdout.readline().strip().rstrip("/")
        print("server", base)

        def tools_ready():
            tools = call(base, "/api/jobs")["tools"]
            line = ", ".join(f"{t['name']}={t['status']}"
                             + (f" {t['done'] * 100 // t['total']}%" if t["status"] == "downloading" and t["total"] else "")
                             + (f" ({t['error']})" if t["error"] else "") for t in tools["items"])
            print("tools:", line, flush=True)
            failed = [t for t in tools["items"] if t["status"] == "error"]
            if failed:
                raise SystemExit("установка не удалась: " + "; ".join(t["error"] for t in failed))
            return tools["ready"] and not tools["installing"] and tools

        tools = wait("компоненты", tools_ready, timeout=1200, every=5)
        print("yt-dlp", tools["version"], [(t["name"], t["source"]) for t in tools["items"]])

        call(base, "/api/settings", {"folder": str(out_dir)})
        for attempt in range(3):  # сеть на CI бывает капризной
            try:
                info = call(base, "/api/info", {"url": CLIP})
                break
            except SystemExit as e:
                print("info failed, retry:", e)
                time.sleep(5)
        else:
            raise SystemExit("превью так и не получилось")
        assert info["kind"] == "video", info
        print("info:", info["title"], [q["height"] for q in info["qualities"]])

        clip = [{"url": info["url"], "title": info["title"]}]
        video = call(base, "/api/download", {"items": clip, "opts": {"mode": "video", "quality": "best", "container": "mp4"}})
        # У клипа нет звука: ждём понятную ошибку, а не трассировку ffmpeg.
        silent = call(base, "/api/download", {"items": clip, "opts": {"mode": "audio", "audio": "mp3"}})
        piece = {"mode": "audio", "audio": "mp3", "start": "1:00", "end": "1:05"}
        audio = call(base, "/api/download", {"items": [{"url": FULL, "title": "Big Buck Bunny"}], "opts": piece})
        ids = set(video["ids"] + silent["ids"] + audio["ids"])

        def finished():
            jobs = [j for j in call(base, "/api/jobs")["jobs"] if j["id"] in ids]
            print("jobs:", [(j["status"], round(j["progress"], 2), j["error"]) for j in jobs], flush=True)
            return all(j["status"] in ("done", "error") for j in jobs) and jobs

        jobs = wait("загрузки", finished, timeout=600)
        failed = [j for j in jobs if j["id"] in silent["ids"]]
        assert failed[0]["status"] == "error" and "нет звук" in failed[0]["error"], failed
        print("ok: немой клип ->", failed[0]["error"])
        jobs = [j for j in jobs if j["id"] not in silent["ids"]]
        for job in jobs:
            assert job["status"] == "done", job
            assert job["file"] and Path(job["file"]).stat().st_size > 10_000, job
            print("ok:", job["file"], Path(job["file"]).stat().st_size)
        suffixes = sorted(Path(j["file"]).suffix for j in jobs)
        assert suffixes == [".mp3", ".mp4"], suffixes
        print("SMOKE OK")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
