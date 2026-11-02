"""Точное вырезание рекламных вставок из готового видео.

yt-dlp режет склейкой ffmpeg: concat-демуксер с точками входа и выхода и `-c copy`.
Демуксер начинает каждый кусок с ключевого кадра до точки реза и отдаёт звук, который
лежит в файле рядом с ним. Эти лишние пакеты на стыке сжимаются в одну точку, но всё
равно проигрываются: после каждого реза звук отстаёт на десятые доли секунды, а видео
начинается с неполного кадра. `--force-keyframes-at-cuts` чинит только картинку.

Поэтому yt-dlp вставки только отмечает главами, а режем мы: видео и звук проходят
через trim и atrim по одним и тем же точкам, главы и субтитры сдвигаем сами.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from collections import deque
from pathlib import Path
from typing import Callable

from . import system

CHAPTER_PREFIX = "[SponsorBlock]"
CHAPTER_TITLE = CHAPTER_PREFIX + ": %(category_names)l"
MIN_PIECE = 0.05  # обрезки короче кадра ничего не дают, а склейку портят
FADE = 0.01       # 10 мс на стыке убирают щелчок и не слышны

Ranges = list[tuple[float, float]]


class CutError(Exception):
    pass


# ---------------------------------------------------------------- расчёты

def keep_ranges(chapters: list[dict], duration: float) -> Ranges:
    """Что оставить: всё, кроме глав SponsorBlock. Пустой список значит «резать нечего»."""
    ads = sorted((max(0.0, float(c["start_time"])), min(duration, float(c["end_time"])))
                 for c in chapters if chapter_title(c).startswith(CHAPTER_PREFIX))
    keep, pos = [], 0.0
    for a, b in ads:
        if a - pos >= MIN_PIECE:
            keep.append((pos, a))
        pos = max(pos, b)
    if duration - pos >= MIN_PIECE:
        keep.append((pos, duration))
    if not ads or keep == [(0.0, duration)]:
        return []
    return keep


def remap(t: float, keep: Ranges) -> float:
    """Где окажется момент t исходного видео после вырезания."""
    out = 0.0
    for a, b in keep:
        if t <= a:
            break
        out += min(t, b) - a
    return out


def chapter_title(c: dict) -> str:
    return str((c.get("tags") or {}).get("title") or "")


def new_chapters(chapters: list[dict], keep: Ranges) -> list[tuple[float, float, str]]:
    """Обычные главы на новой шкале. Разметка рвёт главу вокруг вставки: куски склеиваем обратно."""
    out: list[tuple[float, float, str]] = []
    for c in chapters:
        title = chapter_title(c)
        if title.startswith(CHAPTER_PREFIX):
            continue
        start, end = remap(float(c["start_time"]), keep), remap(float(c["end_time"]), keep)
        if end - start < MIN_PIECE:
            continue
        if out and out[-1][2] == title and start - out[-1][1] < MIN_PIECE:
            out[-1] = (out[-1][0], end, title)
        else:
            out.append((start, end, title))
    # Одна глава на всё видео: её придумал yt-dlp из названия, пользы от неё нет.
    return out if len(out) > 1 else []


def ffmetadata(chapters: list[tuple[float, float, str]]) -> str:
    def esc(s: str) -> str:
        return re.sub(r"([=;#\\\n])", r"\\\1", s)
    lines = [";FFMETADATA1"]
    for start, end, title in chapters:
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={round(start * 1000)}",
                  f"END={round(end * 1000)}", f"title={esc(title)}"]
    return "\n".join(lines) + "\n"


SRT_TIME = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})")
ASS_TIME = re.compile(r"(\d+):(\d\d):(\d\d)\.(\d\d)")


def _secs(m: re.Match, frac_digits: int) -> float:
    h, mnt, s, f = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + int(s) + int(f.ljust(frac_digits, "0")) / 10 ** frac_digits


def _srt_time(t: float) -> str:
    ms = round(t * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _ass_time(t: float) -> str:
    cs = round(t * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def retime_srt(text: str, keep: Ranges) -> str:
    blocks, n = [], 0
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.split("\n")
        i = next((k for k, line in enumerate(lines) if "-->" in line), None)
        if i is None:
            continue
        times = list(SRT_TIME.finditer(lines[i]))
        if len(times) < 2:
            continue
        start, end = (remap(_secs(m, 3), keep) for m in times[:2])
        if end - start <= 0.001:
            continue
        n += 1
        blocks.append("\n".join([str(n), f"{_srt_time(start)} --> {_srt_time(end)}", *lines[i + 1:]]))
    return "\n\n".join(blocks) + "\n" if blocks else ""


def retime_ass(text: str, keep: Ranges) -> str:
    out, cues = [], 0
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.startswith("Dialogue:"):
            head, rest = line.split(":", 1)
            parts = rest.split(",", 3)
            if len(parts) == 4 and ASS_TIME.fullmatch(parts[1].strip()) and ASS_TIME.fullmatch(parts[2].strip()):
                start = remap(_secs(ASS_TIME.fullmatch(parts[1].strip()), 2), keep)
                end = remap(_secs(ASS_TIME.fullmatch(parts[2].strip()), 2), keep)
                if end - start <= 0.001:
                    continue
                parts[1], parts[2] = _ass_time(start), _ass_time(end)
                line = f"{head}:{','.join(parts)}"
                cues += 1
        out.append(line)
    return "\n".join(out) if cues else ""


# ---------------------------------------------------------------- ffmpeg

def probe(ffprobe: str, path: str, env: dict) -> dict:
    p = system.run([ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
                    "-show_chapters", path], timeout=120, env=env)
    if p.returncode != 0:
        raise CutError(p.stderr.strip() or "ffprobe не прочитал файл")
    return json.loads(p.stdout or "{}")


def encoders(ffmpeg: str, env: dict) -> set[str]:
    p = system.run([ffmpeg, "-hide_banner", "-encoders"], timeout=60, env=env)
    return set(re.findall(r"^\s*[VAS][\w.]{5}\s+(\S+)", p.stdout or "", re.M))


def build_cmd(ffmpeg: str, src: str, dst: str, info: dict, keep: Ranges, meta: str | None,
              subs: list[tuple[str, dict]], have: set[str]) -> list[str]:
    streams = info.get("streams") or []
    pics = [s for s in streams if s.get("codec_type") == "video" and (s.get("disposition") or {}).get("attached_pic")]
    video = next((s for s in streams if s.get("codec_type") == "video" and s not in pics), None)
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    mkv = Path(dst).suffix.lower() in (".mkv", ".webm")

    last = len(keep) - 1
    graph, pads = [], []
    for i, (a, b) in enumerate(keep):
        rng = (f"start={a:.6f}" if a > 0 else "") + (f":end={b:.6f}" if i < last else "")
        rng = rng.lstrip(":")
        if video:
            graph.append(f"[0:{video['index']}]trim={rng},setpts=PTS-STARTPTS[v{i}]" if rng
                         else f"[0:{video['index']}]setpts=PTS-STARTPTS[v{i}]")
            pads.append(f"[v{i}]")
        for k, s in enumerate(audio):
            chain = [f"atrim={rng}" if rng else "anull", "asetpts=PTS-STARTPTS"]
            if i > 0:
                chain.append(f"afade=t=in:d={FADE}")
            if i < last:
                chain.append(f"afade=t=out:st={max(0.0, b - a - FADE):.6f}:d={FADE}")
            graph.append(f"[0:{s['index']}]{','.join(chain)}[a{k}_{i}]")
            pads.append(f"[a{k}_{i}]")
    outs = ("[v]" if video else "") + "".join(f"[a{k}]" for k in range(len(audio)))
    graph.append(f"{''.join(pads)}concat=n={len(keep)}:v={1 if video else 0}:a={len(audio)}{outs}")

    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-progress", "pipe:1", "-nostats",
           "-i", src]
    inputs = 1
    meta_input = None
    if meta:
        cmd += ["-f", "ffmetadata", "-i", meta]
        meta_input, inputs = inputs, inputs + 1
    sub_inputs = []
    for path, _ in subs:
        cmd += ["-i", path]
        sub_inputs.append(inputs)
        inputs += 1

    cmd += ["-filter_complex", ";".join(graph)]
    vout = 0
    if video:
        cmd += ["-map", "[v]"]
        cmd += ["-c:v:0", "libx264", "-preset", "veryfast", "-crf", "18"] if "libx264" in have else []
        vout = 1
    for k, s in enumerate(audio):
        cmd += ["-map", f"[a{k}]"]
        cmd += _stream_tags(f"a:{k}", s)
    if audio:
        # В MKV нет списка правок, и задержка кодера AAC (21 мс) остаётся в файле. У Opus она учтена.
        cmd += ["-c:a", "libopus", "-b:a", "160k"] if mkv and "libopus" in have else ["-c:a", "aac", "-b:a", "192k"]
    for s in pics:
        cmd += ["-map", f"0:{s['index']}", f"-c:v:{vout}", "copy", f"-disposition:v:{vout}", "attached_pic"]
        vout += 1
    for j, (n, (_, s)) in enumerate(zip(sub_inputs, subs)):
        cmd += ["-map", f"{n}:0"] + _stream_tags(f"s:{j}", s)
    if subs:
        cmd += ["-c:s", "copy" if mkv else "mov_text"]
    if mkv:
        cmd += ["-map", "0:t?", "-c:t", "copy"]
    cmd += ["-map_metadata", "0", "-map_chapters", str(meta_input) if meta_input is not None else "-1", dst]
    return cmd


def _stream_tags(spec: str, s: dict) -> list[str]:
    tags = s.get("tags") or {}
    out = []
    for key in ("language", "title"):
        if tags.get(key):
            out += [f"-metadata:s:{spec}", f"{key}={tags[key]}"]
    return out


def remove_ads(path: str, ffmpeg: str, ffprobe: str, env: dict, work: Path,
               on_proc: Callable[[subprocess.Popen | None], None] = lambda p: None,
               on_progress: Callable[[float], None] = lambda f: None) -> bool:
    """Вырезает отмеченные вставки на месте. False, если резать нечего."""
    info = probe(ffprobe, path, env)
    duration = float((info.get("format") or {}).get("duration") or 0)
    keep = keep_ranges(info.get("chapters") or [], duration)
    if not duration or not keep:
        return False

    work.mkdir(parents=True, exist_ok=True)
    chapters = new_chapters(info.get("chapters") or [], keep)
    meta = None
    if chapters:
        meta = str(work / "chapters.txt")
        Path(meta).write_text(ffmetadata(chapters), encoding="utf-8")

    subs = []
    for j, s in enumerate(x for x in info.get("streams") or [] if x.get("codec_type") == "subtitle"):
        ass = s.get("codec_name") in ("ass", "ssa")
        raw = work / f"sub{j}.{'ass' if ass else 'srt'}"
        p = system.run([ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-i", path,
                        "-map", f"0:{s['index']}", "-c:s", "ass" if ass else "srt", str(raw)], timeout=300, env=env)
        if p.returncode != 0 or not raw.exists():
            continue  # картинки-субтитры (PGS, DVD) в текст не переводятся: их просто не будет
        text = raw.read_text(encoding="utf-8", errors="replace")
        text = retime_ass(text, keep) if ass else retime_srt(text, keep)
        if text:
            fixed = work / f"sub{j}.cut{raw.suffix}"
            fixed.write_text(text, encoding="utf-8")
            subs.append((str(fixed), s))

    src = Path(path)
    dst = src.with_name(f"{src.stem}.cut.temp{src.suffix}")
    cmd = build_cmd(ffmpeg, path, str(dst), info, keep, meta, subs, encoders(ffmpeg, env))
    total = sum(b - a for a, b in keep)
    tail: deque[str] = deque(maxlen=40)
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
                                **system.popen_flags())
        on_proc(proc)
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_us="):
                us = line.split("=", 1)[1]
                if us.isdigit() and total:
                    on_progress(min(int(us) / 1e6 / total, 1.0))
            elif line and "=" not in line:
                tail.append(line)
        rc = proc.wait()
    except OSError as e:
        tail.append(str(e))
        rc = -1
    finally:
        on_proc(None)
    if rc != 0 or not dst.exists():
        dst.unlink(missing_ok=True)
        raise CutError("\n".join(tail) or f"ffmpeg завершился с кодом {rc}")
    os.replace(dst, src)
    return True
