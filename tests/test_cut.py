"""Вырезание рекламы: расчёты без ffmpeg и настоящая нарезка с проверкой синхрона."""
import array
import json
import os
import shutil
import subprocess

import pytest

from kachalka import cut

AD = cut.CHAPTER_PREFIX + ": Sponsor"


def ch(start, end, title):
    return {"start_time": str(start), "end_time": str(end), "tags": {"title": title}}


def test_keep_ranges_merges_and_skips_slivers():
    chapters = [ch(0, 10, "Intro"), ch(10, 20, AD), ch(19, 25, AD), ch(25, 59.98, "Main"), ch(59.98, 60, AD)]
    assert cut.keep_ranges(chapters, 60) == [(0.0, 10.0), (25.0, 59.98)]
    assert cut.keep_ranges([ch(0, 60, "Main")], 60) == []
    assert cut.keep_ranges([ch(0, 30, AD), ch(30, 60, "Main")], 60) == [(30.0, 60.0)]


def test_remap_and_chapters():
    keep = [(0.0, 10.0), (20.0, 60.0)]
    assert cut.remap(5, keep) == 5
    assert cut.remap(15, keep) == 10  # внутри вырезанного куска: прилипает к стыку
    assert cut.remap(30, keep) == 20
    # yt-dlp разрезал «Main» вставкой: после вырезания это снова одна глава.
    chapters = [ch(0, 5, "Intro"), ch(5, 10, "Main"), ch(10, 20, AD), ch(20, 40, "Main"), ch(40, 60, "End")]
    assert cut.new_chapters(chapters, keep) == [(0, 5, "Intro"), (5, 30, "Main"), (30, 50, "End")]
    # Единственная глава из названия видео не нужна.
    assert cut.new_chapters([ch(0, 10, "Video"), ch(10, 20, AD), ch(20, 60, "Video")], keep) == []


def test_ffmetadata_escapes():
    text = cut.ffmetadata([(0, 1.5, "a=b;c#d")])
    assert "START=0\nEND=1500\ntitle=a\\=b\\;c\\#d" in text


def test_retime_subtitles():
    keep = [(0.0, 10.0), (20.0, 60.0)]
    srt = ("1\n00:00:01,000 --> 00:00:02,000\nдо\n\n"
           "2\n00:00:12,000 --> 00:00:15,000\nреклама\n\n"
           "3\n00:00:09,000 --> 00:00:21,500\nчерез стык\n\n"
           "4\n00:00:30,000 --> 00:00:31,250\nпосле\n")
    assert cut.retime_srt(srt, keep) == (
        "1\n00:00:01,000 --> 00:00:02,000\nдо\n\n"
        "2\n00:00:09,000 --> 00:00:11,500\nчерез стык\n\n"
        "3\n00:00:20,000 --> 00:00:21,250\nпосле\n")
    ass = ("[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
           "Dialogue: 0,0:00:12.00,0:00:15.00,Default,,0,0,0,,реклама\n"
           "Dialogue: 0,0:00:30.00,0:00:31.25,Default,,0,0,0,,после, с запятой")
    out = cut.retime_ass(ass, keep)
    assert "реклама" not in out
    assert "Dialogue: 0,0:00:20.00,0:00:21.25,Default,,0,0,0,,после, с запятой" in out


# ---------------------------------------------------------------- с ffmpeg

FFMPEG, FFPROBE = shutil.which("ffmpeg"), shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="нужен ffmpeg")
ADS = [(13.3, 21.7), (37.1, 44.9)]  # нарочно между ключевыми кадрами


def make_source(tmp_path, ext):
    """60 секунд: раз в секунду белая вспышка и щелчок 1 кГц в один и тот же момент. Ключевой кадр раз в 10 с."""
    base = tmp_path / "base.mp4"
    subprocess.run([
        FFMPEG, "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=black:s=160x90:r=25:d=60,geq=lum='if(lt(mod(T\\,1)\\,0.04)\\,255\\,16)':cb=128:cr=128",
        "-f", "lavfi", "-i", "aevalsrc='if(lt(mod(t\\,1)\\,0.04)\\,sin(2*PI*1000*t)\\,0)':s=48000:d=60",
        "-c:v", "libx264", "-g", "250", "-keyint_min", "250", "-sc_threshold", "0", "-c:a", "aac", str(base),
    ], check=True)
    chapters = [(0, 13.3, "Начало"), (*ADS[0], AD), (21.7, 30, "Начало"), (30, 37.1, "Суть"),
                (*ADS[1], AD), (44.9, 60, "Конец")]
    meta = tmp_path / "meta.txt"
    meta.write_text(cut.ffmetadata(chapters), encoding="utf-8")
    srt = tmp_path / "subs.srt"
    srt.write_text("1\n00:00:05,000 --> 00:00:06,000\nпривет\n\n2\n00:00:15,000 --> 00:00:16,000\nреклама\n\n"
                   "3\n00:00:50,000 --> 00:00:51,000\nпока\n", encoding="utf-8")
    src = tmp_path / f"video.{ext}"
    subprocess.run([
        FFMPEG, "-loglevel", "error", "-y", "-i", str(base), "-f", "ffmetadata", "-i", str(meta), "-i", str(srt),
        "-map", "0", "-map", "2", "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text" if ext == "mp4" else "srt",
        "-metadata:s:s:0", "language=rus", "-metadata", "title=Тест", "-map_chapters", "1", str(src),
    ], check=True)
    return src


def flashes_and_clicks(path):
    out = subprocess.run([FFPROBE, "-v", "error", "-f", "lavfi", f"movie={path.name},signalstats",
                          "-show_entries", "frame=pts_time:frame_tags=lavfi.signalstats.YAVG", "-of", "csv=p=0"],
                         capture_output=True, text=True, cwd=path.parent, check=True).stdout
    flashes, prev = [], 0.0
    for line in out.split():
        t, y = map(float, line.split(",")[:2])
        if y > 128 >= prev:
            flashes.append(t)
        prev = y
    pcm = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "8000",
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    clicks, last = [], -1.0
    for i, x in enumerate(array.array("h", pcm)):
        if abs(x) > 3000 and i / 8000 - last > 0.1:
            clicks.append(i / 8000)
            last = i / 8000
    return flashes, clicks


@needs_ffmpeg
@pytest.mark.parametrize("ext", ["mp4", "mkv"])
def test_remove_ads_keeps_sync(tmp_path, ext):
    src = make_source(tmp_path, ext)
    env = dict(os.environ)
    assert cut.remove_ads(str(src), FFMPEG, FFPROBE, env, tmp_path / "work")

    info = json.loads(subprocess.run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format",
                                      "-show_streams", "-show_chapters", str(src)],
                                     capture_output=True, text=True, check=True).stdout)
    kept = 60 - sum(b - a for a, b in ADS)
    assert float(info["format"]["duration"]) == pytest.approx(kept, abs=0.1)
    assert info["format"]["tags"].get("title") == "Тест"
    assert [(round(float(c["start_time"]), 1), c["tags"]["title"]) for c in info["chapters"]] == \
        [(0, "Начало"), (21.6, "Суть"), (28.7, "Конец")]

    # Каждая вспышка совпадает со своим щелчком, и их ровно столько, сколько секунд осталось.
    flashes, clicks = flashes_and_clicks(src)
    expected = [t for t in range(60) if not any(a <= t < b for a, b in ADS)]
    assert len(flashes) == len(clicks) == len(expected)
    for f, c in zip(flashes, clicks):
        assert abs(f - c) < 0.025, (flashes, clicks)  # не больше кадра (40 мс), с запасом

    sub = [s for s in info["streams"] if s["codec_type"] == "subtitle"]
    assert len(sub) == 1 and sub[0]["tags"].get("language") == "rus"
    srt = subprocess.run([FFMPEG, "-v", "error", "-i", str(src), "-map", "0:s:0", "-f", "srt", "-"],
                         capture_output=True, text=True, check=True).stdout
    assert "привет" in srt and "пока" in srt and "реклама" not in srt
    cues = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "s", "-show_entries",
                           "packet=pts_time,duration_time", "-of", "csv=p=0", str(src)],
                          capture_output=True, text=True, check=True).stdout.split()
    # Пустые промежутки mov_text тоже пакеты: берём только секундные реплики.
    starts = [float(c.split(",")[0]) for c in cues if c.endswith(",1.000000")]
    # 50 с минус 16.2 с вырезанного. MKV сдвигает поток на задержку кодера, это ~20 мс.
    assert starts == [pytest.approx(5.0, abs=0.03), pytest.approx(33.8, abs=0.03)]

    # Второй проход ничего не трогает: глав SponsorBlock в файле больше нет.
    assert not cut.remove_ads(str(src), FFMPEG, FFPROBE, env, tmp_path / "work")
