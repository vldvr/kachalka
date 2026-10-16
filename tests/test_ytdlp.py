"""Превью, дорожки, сборка команды и ошибки yt-dlp. Сеть не нужна."""
import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from kachalka import ytdlp
from kachalka.jobs import Job
from kachalka.settings import ApiError, clean_opts


def fmt(fid, ext, vcodec, acodec, height=None, lang=None, pref=None, note="", size=1000):
    return {"format_id": fid, "ext": ext, "vcodec": vcodec, "acodec": acodec, "height": height,
            "width": height and height * 16 // 9, "language": lang, "language_preference": pref,
            "format_note": note, "filesize": size, "protocol": "https", "url": f"https://example.invalid/{fid}"}


VIDEO = {
    "id": "abcdefghijk", "title": "Test video", "extractor": "youtube", "extractor_key": "Youtube",
    "webpage_url": "https://www.youtube.com/watch?v=abcdefghijk", "duration": 600,
    "formats": [
        fmt("137", "mp4", "avc1.640028", "none", 1080, note="1080p", size=90_000_000),
        fmt("248", "webm", "vp9", "none", 1080, note="1080p", size=70_000_000),
        fmt("136", "mp4", "avc1.4d401f", "none", 720, note="720p", size=40_000_000),
        fmt("140-0", "m4a", "none", "mp4a.40.2", lang="en-US", pref=10,
            note="English (United States) original (default), medium", size=9_000_000),
        fmt("251-0", "webm", "none", "opus", lang="en-US", pref=10,
            note="English (United States) original (default), medium", size=8_000_000),
        fmt("140-1", "m4a", "none", "mp4a.40.2", lang="ru", pref=-1, note="Russian (dubbed-auto), medium", size=9_100_000),
        fmt("251-1", "webm", "none", "opus", lang="ru", pref=-1, note="Russian (dubbed-auto), medium", size=8_100_000),
        fmt("140-2", "m4a", "none", "mp4a.40.2", lang="de", pref=-1, note="German, medium", size=9_200_000),
        fmt("140-3", "m4a", "none", "mp4a.40.2", lang="en-desc", pref=-10, note="English descriptive", size=9_300_000),
    ],
}


@pytest.mark.parametrize("raw, expected", [
    ("dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
    ("youtu.be/abc", "https://youtu.be/abc"),
    ("https://www.youtube.com/@channel", "https://www.youtube.com/@channel/videos"),
    ("youtube.com/channel/UC123/", "https://www.youtube.com/channel/UC123/videos"),
    ("https://www.youtube.com/@channel/shorts", "https://www.youtube.com/@channel/shorts"),
])
def test_normalize_url(raw, expected):
    assert ytdlp.normalize_url(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "not a link"])
def test_normalize_url_rejects_garbage(raw):
    with pytest.raises(ApiError):
        ytdlp.normalize_url(raw)


@pytest.mark.parametrize("stderr, hint, fragment", [
    ("ERROR: [youtube] x: Sign in to confirm you're not a bot.", "cookies", "не бот"),
    ("ERROR: [youtube] x: Sign in to confirm your age.", "cookies", "18+"),
    ("ERROR: [youtube] x: Private video. Sign in if you've been granted access", "cookies", "приватное"),
    ("ERROR: Could not copy Chrome cookie database.", "cookies", "Firefox"),
    ("ERROR: Postprocessing: WARNING: unable to obtain file audio codec with ffprobe", "", "нет звук"),
    ("ERROR: Unable to download webpage: timed out", "", "Нет связи"),
    ("ERROR: [youtube] x: nsig extraction failed", "update", "обновление"),
])
def test_explain_error(stderr, hint, fragment):
    message, got_hint, raw = ytdlp.explain_error("WARNING: something\n" + stderr)
    assert got_hint == hint
    assert fragment in message
    assert raw and not raw.startswith("ERROR")


def test_summarize_video_qualities_and_tracks():
    info = ytdlp.summarize(VIDEO, VIDEO["webpage_url"])
    assert [q["height"] for q in info["qualities"]] == [1080, 720]
    q1080 = info["qualities"][0]
    assert q1080["size_mp4"] > q1080["size_mkv"]  # mp4 считается по H.264, mkv по VP9
    tracks = info["audio_tracks"]
    assert [(t["code"], t["kind"]) for t in tracks] == [
        ("en-US", "original"), ("de", ""), ("ru", "dub_auto"), ("en-desc", "desc")]
    assert tracks[0]["label"] == "Английский"  # регион не нужен: второго английского нет


def test_summarize_single_language_has_no_track_picker():
    single = dict(VIDEO, formats=[f for f in VIDEO["formats"] if f.get("language") in (None, "en-US")])
    assert ytdlp.summarize(single, "u")["audio_tracks"] == []


def test_summarize_playlist():
    data = {"_type": "playlist", "title": "Лекции", "channel": "Кафедра", "entries": [
        {"_type": "url", "ie_key": "Youtube", "id": "aaaaaaaaaaa", "url": "https://www.youtube.com/watch?v=aaaaaaaaaaa",
         "title": "Первая", "duration": 100, "thumbnails": [{"url": "https://i.ytimg.com/a.jpg", "width": 336}]},
        {"_type": "url", "ie_key": "Youtube", "id": "bbbbbbbbbbb", "url": "bbbbbbbbbbb", "title": "Вторая"},
        None,
        {"_type": "url", "ie_key": "YoutubeTab", "url": "https://www.youtube.com/@x/shorts"},
    ]}
    info = ytdlp.summarize(data, "u")
    assert info["kind"] == "playlist"
    assert [e["url"] for e in info["entries"]] == [
        "https://www.youtube.com/watch?v=aaaaaaaaaaa", "https://www.youtube.com/watch?v=bbbbbbbbbbb"]
    assert info["entries"][1]["thumb"].endswith("/bbbbbbbbbbb/mqdefault.jpg")


def test_playlist_of_playlists_is_explained():
    with pytest.raises(ApiError, match="подборка плейлистов"):
        ytdlp.summarize({"_type": "playlist", "entries": [{"ie_key": "YoutubeTab", "url": "x"}]}, "u")


def test_clean_opts_validates():
    assert clean_opts({"audio_both": True})["audio_both"] is False
    assert clean_opts({"audio_lang": "ru", "audio_orig": "ru", "audio_both": True})["audio_both"] is False
    assert clean_opts({"quality": "9999"})["quality"] == "1080"
    for bad in ({"audio_lang": "ru'; rm -rf"}, {"start": "полторы минуты"}):
        with pytest.raises(ApiError):
            clean_opts(bad)


TOOLS = SimpleNamespace(ytdlp="yt-dlp", ytdlp_args=lambda: [])


def args_for(opts, group=None):
    job = Job(url=VIDEO["webpage_url"], opts=clean_opts(opts), folder="/tmp/out", group=group, index=3)
    cmd = ytdlp.build_cmd(job, {"subs_langs": "ru.*", "cookies": "", "proxy": ""}, TOOLS, __import__("pathlib").Path("/tmp"))
    picked = []
    for flag in ("-f", "-S"):
        if flag in cmd:
            picked += [flag, cmd[cmd.index(flag) + 1]]
    if "--audio-multistreams" in cmd:
        picked.append("--audio-multistreams")
    return cmd, picked


def test_build_cmd_playlist_output_and_sections():
    cmd, _ = args_for({"mode": "video", "start": "1:00", "end": "2:00"}, group="Мой: плейлист 100%")
    assert cmd[cmd.index("-o") + 1] == "Мой плейлист 100%%/003 - %(title)s.%(ext)s"
    assert "*1:00-2:00" in cmd
    assert cmd[-2:] == ["--", VIDEO["webpage_url"]]


CASES = [
    ({"mode": "video", "quality": "1080", "container": "mp4"}, None, "137+140-0"),
    ({"mode": "video", "quality": "1080", "container": "mp4", "audio_lang": "ru"}, None, "137+140-1"),
    ({"mode": "video", "quality": "1080", "container": "mp4", "audio_lang": "ru", "audio_orig": "en-US",
      "audio_both": True}, None, "137+140-1+140-0"),
    ({"mode": "video", "quality": "720", "container": "mkv", "audio_lang": "de"}, None, "136+140-2"),
    ({"mode": "audio", "audio": "mp3", "audio_lang": "ru"}, None, "251-1"),
    ({"mode": "audio", "audio": "opus"}, None, "251-0"),
    ({"mode": "audio", "audio": "m4a", "audio_lang": "en"}, "Плейлист", "140-0"),
    ({"mode": "video", "quality": "1080", "audio_lang": "fr"}, "Плейлист", "137+140-0"),
]


@pytest.mark.skipif(not shutil.which("yt-dlp"), reason="нужен yt-dlp")
@pytest.mark.parametrize("opts, group, expected", CASES)
def test_format_selection_with_real_ytdlp(tmp_path, opts, group, expected):
    """Настоящий yt-dlp выбирает форматы из сохранённого ответа: проверяем, что фильтры и сортировка верные."""
    info = tmp_path / "info.json"
    info.write_text(json.dumps(VIDEO))
    _, picked = args_for(opts, group)
    out = subprocess.run(["yt-dlp", "--load-info-json", str(info), "--simulate", "--no-warnings",
                          "--print", "format_id", *picked], capture_output=True, text=True, timeout=120)
    assert out.stdout.strip() == expected, out.stderr
