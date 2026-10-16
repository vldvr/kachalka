"""Очередь загрузок: запуск yt-dlp, разбор прогресса, история."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque
from pathlib import Path

from . import system
from .settings import DEFAULT_OPTS, ApiError, Settings
from .tools import Tools
from .ytdlp import PP_STAGES, build_cmd, explain_error, normalize_url, num

log = logging.getLogger(__name__)

ACTIVE = ("starting", "running", "processing")
FINISHED = ("done", "canceled", "error")
HISTORY_LIMIT = 300
SAVED_FIELDS = ("id", "seq", "batch", "url", "title", "thumb", "duration", "channel", "group", "index",
                "opts", "template", "folder", "status", "progress", "downloaded", "total", "file",
                "error", "hint", "raw_error", "created", "finished", "existed", "force")


class Job:
    def __init__(self, **kw):
        self.id = uuid.uuid4().hex[:12]
        self.seq = self.batch = 0
        self.url = self.title = ""
        self.thumb = self.channel = self.group = None
        self.duration = None
        self.index = 0
        self.opts = dict(DEFAULT_OPTS)
        self.template = "title"
        self.folder = ""
        self.status = "queued"
        self.progress = 0.0
        self.downloaded = self.total = 0
        self.speed = self.eta = None
        self.stage = ""
        self.file = ""
        self.error = self.hint = self.raw_error = ""
        self.created = time.time()
        self.finished = None
        self.existed = self.force = False
        self.proc: subprocess.Popen | None = None
        self.cancel_requested = False
        for k, v in kw.items():
            if k in SAVED_FIELDS:
                setattr(self, k, v)

    def reset(self):
        self.status = "queued"
        self.progress, self.downloaded, self.total = 0.0, 0, 0
        self.speed = self.eta = None
        self.stage = self.error = self.hint = self.raw_error = self.file = ""
        self.finished = None
        self.existed = self.force = False
        self.cancel_requested = False

    def to_dict(self, live: bool = False) -> dict:
        d = {k: getattr(self, k) for k in SAVED_FIELDS}
        if live:
            d.update(speed=self.speed, eta=self.eta, stage=self.stage,
                     file_exists=bool(self.file) and os.path.exists(self.file))
        return d


def drop_temp(path: Path):
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink(missing_ok=True)


class Manager:
    def __init__(self, paths: system.Paths, settings: Settings, tools: Tools):
        self.paths = paths
        self.settings = settings
        self.tools = tools
        self.jobs: dict[str, Job] = {}
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.seq = 0
        for d in system.load_json(paths.jobs, []):
            job = Job(**d)
            if job.status in ACTIVE or job.status == "queued":
                job.status, job.stage = "interrupted", ""
            self.jobs[job.id] = job
            self.seq = max(self.seq, job.seq, job.batch)
        # Недокачанные куски задач, которых больше нет в списке, только занимают место.
        if paths.tmp.is_dir():
            for item in paths.tmp.iterdir():
                if item.name not in self.jobs:
                    drop_temp(item)
        threading.Thread(target=self.scheduler, name="scheduler", daemon=True).start()

    # -- состояние
    def list(self) -> list[dict]:
        with self.lock:
            jobs = sorted(self.jobs.values(), key=lambda j: (-j.batch, j.seq))
            return [j.to_dict(live=True) for j in jobs]

    def busy(self) -> bool:
        with self.lock:
            return any(j.status in ACTIVE or j.status == "queued" for j in self.jobs.values())

    def save(self):
        with self.lock:
            jobs = sorted(self.jobs.values(), key=lambda j: (j.batch, j.seq))[-HISTORY_LIMIT:]
            data = [j.to_dict() for j in jobs]
        system.save_json(self.paths.jobs, data)

    # -- действия
    def add(self, items: list[dict], group: str | None, opts: dict) -> list[str]:
        s = self.settings.get()
        with self.lock:
            self.seq += 1
            batch = self.seq
            ids = []
            for it in items:
                self.seq += 1
                job = Job(
                    seq=self.seq, batch=batch, url=normalize_url(it.get("url")),
                    title=str(it.get("title") or "")[:300] or it.get("url"),
                    thumb=it.get("thumb"), duration=it.get("duration"), channel=it.get("channel"),
                    group=group, index=int(it.get("index") or 0) if group else 0,
                    opts=opts, template=s["template"], folder=s["folder"],
                )
                self.jobs[job.id] = job
                ids.append(job.id)
        self.save()
        self.wake.set()
        return ids

    def get(self, jid: str) -> Job:
        job = self.jobs.get(jid)
        if not job:
            raise ApiError("Такой загрузки нет.", status=404)
        return job

    def cancel(self, jid: str):
        with self.lock:
            job = self.get(jid)
            if job.status == "queued":
                job.status, job.finished = "canceled", time.time()
            elif job.status in ACTIVE:
                job.cancel_requested = True
                job.stage = "Останавливаю"
                if job.proc:
                    system.kill_tree(job.proc)
        self.save()

    def retry(self, jid: str, force: bool = False):
        with self.lock:
            job = self.get(jid)
            if job.status in ("error", "canceled", "interrupted", "done"):
                job.reset()
                job.force = force
        self.save()
        self.wake.set()

    def remove(self, jid: str):
        with self.lock:
            job = self.get(jid)
            if job.status in ACTIVE:
                raise ApiError("Сначала останови загрузку.")
            del self.jobs[jid]
        drop_temp(self.paths.tmp / jid)
        self.save()

    def clear(self):
        with self.lock:
            for jid in [j.id for j in self.jobs.values() if j.status in FINISHED]:
                del self.jobs[jid]
                drop_temp(self.paths.tmp / jid)
        self.save()

    def stop_all(self):
        with self.lock:
            for job in self.jobs.values():
                if job.proc:
                    job.cancel_requested = True
                    system.kill_tree(job.proc)
                if job.status in ACTIVE or job.status == "queued":
                    job.status = "interrupted"
        self.save()

    # -- выполнение
    def scheduler(self):
        while True:
            self.wake.wait(timeout=1.0)
            self.wake.clear()
            # Пока компоненты не скачаны, задачи ждут в очереди.
            if not self.tools.ready:
                continue
            with self.lock:
                limit = self.settings.data["parallel"]
                running = sum(1 for j in self.jobs.values() if j.status in ACTIVE)
                for job in sorted(self.jobs.values(), key=lambda j: (j.batch, j.seq)):
                    if running >= limit:
                        break
                    if job.status == "queued":
                        job.status, job.stage = "starting", "Подключаюсь"
                        running += 1
                        threading.Thread(target=self.run, args=(job,), name=f"job-{job.id}", daemon=True).start()

    def run(self, job: Job):
        s = self.settings.get()
        started = time.time()
        tail: deque[str] = deque(maxlen=80)
        phase = {"fid": None, "done": 0, "cur_total": 0, "index": 0}
        sizes: list[float] = []
        try:
            Path(job.folder).mkdir(parents=True, exist_ok=True)
            self.paths.tmp.mkdir(parents=True, exist_ok=True)
            with self.lock:
                if job.cancel_requested:
                    raise InterruptedError
                job.proc = subprocess.Popen(
                    build_cmd(job, s, self.tools, self.paths.tmp),
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                    env=self.tools.env(), **system.popen_flags(),
                )
            for line in job.proc.stdout:
                self._line(job, line.rstrip("\r\n"), phase, sizes, tail)
            rc = job.proc.wait()
        except InterruptedError:
            rc = -1
        except OSError as e:
            tail.append(f"ERROR: {e}")
            rc = -1
        with self.lock:
            job.proc = None
            job.speed = job.eta = None
            job.finished = time.time()
            if job.cancel_requested:
                job.status, job.stage = "canceled", ""
            elif rc == 0:
                job.status, job.stage, job.progress = "done", "", 1.0
                drop_temp(self.paths.tmp / job.id)
                if job.file and os.path.exists(job.file):
                    job.total = job.downloaded = os.path.getsize(job.file)
                    # yt-dlp молча пропускает файл с тем же именем: ни строки прогресса,
                    # а сам файл старше задачи. Тогда честно говорим, что ничего не качали.
                    job.existed = phase["fid"] is None and os.path.getmtime(job.file) < started - 1
            else:
                job.status, job.stage = "error", ""
                job.error, job.hint, job.raw_error = explain_error("\n".join(tail))
                log.warning("job %s failed: %s", job.id, job.raw_error)
        self.save()
        self.wake.set()

    def _line(self, job: Job, line: str, phase: dict, sizes: list, tail: deque):
        if not line:
            return
        if line.startswith("DL|"):
            self._progress(job, line.split("|"), phase, sizes)
        elif line.startswith("PP|"):
            parts = line.split("|")
            name = parts[2] if len(parts) > 2 else ""
            job.stage = next((text for key, text in PP_STAGES if key in name), "Обрабатываю файл")
            # Обложку yt-dlp готовит ещё до скачивания: это не постобработка.
            if phase["fid"] is not None:
                job.status = "processing"
                job.speed = job.eta = None
        elif line.startswith("SIZES|"):
            a, b, total = (line.split("|") + ["", "", ""])[1:4]
            sizes[:] = [x for x in (num(a), num(b)) if x] or ([num(total)] if num(total) else [])
            if sizes:
                job.total = int(sum(sizes))
        elif line.startswith("TITLE|"):
            title = line.split("|", 1)[1].strip()
            if title and title != "NA" and (not job.title or job.title == job.url):
                job.title = title
        elif line.startswith("FILE|"):
            job.file = line.split("|", 1)[1].strip()
        else:
            tail.append(line)

    @staticmethod
    def _progress(job: Job, parts: list[str], phase: dict, sizes: list):
        parts += [""] * (8 - len(parts))
        _, _status, done, total, estimate, speed, eta, fid = parts[:8]
        done = num(done) or 0
        total = num(total) or num(estimate) or 0
        if fid != phase["fid"]:
            if phase["fid"] is not None:
                phase["done"] += phase["cur_total"]
                phase["index"] += 1
            phase["fid"] = fid
        phase["cur_total"] = max(total, done)
        job.status = "running"
        job.stage = ""
        job.speed = num(speed)
        job.eta = int(num(eta)) if num(eta) is not None else None
        job.downloaded = int(phase["done"] + done)
        expected = sum(sizes) if sizes else 0
        if expected and expected >= job.downloaded:
            job.total = int(max(expected, phase["done"] + phase["cur_total"]))
            job.progress = min(job.downloaded / job.total, 0.999)
        elif total:
            parts_count = max(len(sizes), phase["index"] + 1)
            job.total = int(phase["done"] + total)
            job.progress = min((phase["index"] + done / total) / parts_count, 0.999)
