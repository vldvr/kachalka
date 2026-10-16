"""Всё про yt-dlp: превью ссылки, сборка команды загрузки и понятные ошибки."""
from __future__ import annotations

import json
import re
import subprocess
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from . import system
from .settings import TEMPLATES, ApiError

ERROR_RULES = [
    (r"confirm your age|age-restricted|inappropriate for some users",
     "Видео 18+. Чтобы его скачать, включи в настройках куки браузера, где ты вошёл в YouTube.", "cookies"),
    (r"not a bot|Sign in to confirm",
     "YouTube просит подтвердить, что ты не бот. Включи в настройках куки браузера, где ты вошёл в YouTube.", "cookies"),
    (r"Private video",
     "Это приватное видео. Его можно скачать только с куками аккаунта, у которого есть доступ.", "cookies"),
    (r"members-only|Join this channel",
     "Видео только для спонсоров канала. Нужны куки аккаунта со спонсорством.", "cookies"),
    (r"Binarycookies|Cookies\.binarycookies|Operation not permitted",
     "Нет доступа к кукам Safari. Дай Качалке «Полный доступ к диску» в Системных настройках или выбери другой браузер.",
     "cookies"),
    (r"Could not copy .*cookie database|App-Bound|app_bound|v20 cookies",
     "Chrome и Edge в Windows не отдают куки другим программам. Войди в YouTube в Firefox и выбери его в настройках.",
     "cookies"),
    (r"could not find .* cookies database|failed to decrypt|cookie.*(keyring|keychain)|Unsupported browser",
     "Не получилось прочитать куки браузера. Проверь, что браузер установлен и ты в нём вошёл в YouTube.", "cookies"),
    (r"HTTP Error 429|Too Many Requests",
     "YouTube временно ограничил запросы с твоего адреса. Подожди немного или включи куки браузера.", "cookies"),
    (r"Requested format is not available",
     "Такого качества у этого видео нет. Выбери другое.", ""),
    (r"live event will begin|Premieres in|is_upcoming|This live event",
     "Трансляция ещё не началась. Попробуй, когда она пойдёт.", ""),
    (r"Video unavailable|This video is not available|has been removed|video is unavailable",
     "Видео недоступно: его удалили, скрыли или заблокировали в регионе.", ""),
    (r"Unsupported URL",
     "Эту ссылку yt-dlp не понимает. Нужна ссылка на видео, плейлист или канал.", ""),
    (r"is not a valid URL",
     "Это не похоже на ссылку.", ""),
    (r"Unable to download (webpage|API page)|Connection refused|timed out|Network is unreachable|"
     r"nodename nor servname|Name or service not known|Connection reset|Failed to resolve|getaddrinfo failed",
     "Нет связи с сайтом. Проверь интернет или прокси в настройках.", ""),
    (r"ffmpeg (is )?not (found|installed)|ffprobe.*not found",
     "Не найден ffmpeg. Открой настройки и нажми «Проверить компоненты».", "tools"),
    (r"No space left on device|There is not enough space",
     "На диске закончилось место.", ""),
    (r"unable to obtain file audio codec|does not contain any (audio|stream)|Output file #0 does not contain",
     "В этом видео нет звуковой дорожки, вытаскивать нечего.", ""),
    (r"thumbnail embedding|EmbedThumbnail",
     "Не получилось встроить обложку в этот файл. Выключи «Встроить обложку» в разделе «Ещё настройки» и скачай снова.", ""),
    (r"Conversion failed|ffmpeg exited with code|Error opening (input|output)",
     "ffmpeg не смог собрать файл. Попробуй другой формат: MKV вместо MP4 или наоборот.", ""),
    (r"Signature extraction failed|nsig extraction failed|Unable to extract|n challenge|"
     r"Please report this issue|player response|JavaScript runtime",
     "yt-dlp не разобрался со страницей. Обычно помогает обновление yt-dlp.", "update"),
]

PP_STAGES = [
    ("Merger", "Склеиваю видео и звук"),
    ("ExtractAudio", "Достаю звук"),
    ("EmbedSubtitle", "Встраиваю субтитры"),
    ("ThumbnailsConvertor", "Готовлю обложку"),
    ("EmbedThumbnail", "Встраиваю обложку"),
    ("SponsorBlock", "Ищу рекламные вставки"),
    ("ModifyChapters", "Вырезаю рекламные вставки"),
    ("Metadata", "Записываю название и главы"),
    ("MoveFiles", "Переношу файл в папку"),
    ("Fixup", "Чиню контейнер"),
]

LANG_NAMES = {
    "ru": "Русский", "en": "Английский", "de": "Немецкий", "fr": "Французский", "es": "Испанский",
    "it": "Итальянский", "pt": "Португальский", "ja": "Японский", "ko": "Корейский", "zh": "Китайский",
    "hi": "Хинди", "ar": "Арабский", "tr": "Турецкий", "pl": "Польский", "uk": "Украинский",
    "nl": "Нидерландский", "id": "Индонезийский", "vi": "Вьетнамский", "th": "Тайский", "sv": "Шведский",
    "cs": "Чешский", "he": "Иврит", "iw": "Иврит", "fa": "Персидский", "ro": "Румынский", "hu": "Венгерский",
    "el": "Греческий", "fi": "Финский", "da": "Датский", "no": "Норвежский", "nb": "Норвежский",
    "be": "Белорусский", "kk": "Казахский", "uz": "Узбекский", "ka": "Грузинский", "hy": "Армянский",
    "az": "Азербайджанский", "bg": "Болгарский", "sr": "Сербский", "hr": "Хорватский", "sk": "Словацкий",
    "lt": "Литовский", "lv": "Латышский", "et": "Эстонский", "ms": "Малайский", "fil": "Филиппинский",
    "bn": "Бенгальский", "ta": "Тамильский", "te": "Телугу", "ur": "Урду", "ml": "Малаялам", "mr": "Маратхи",
}
REGIONS = {
    "US": "США", "GB": "Британия", "AU": "Австралия", "CA": "Канада", "IN": "Индия", "BR": "Бразилия",
    "PT": "Португалия", "ES": "Испания", "419": "Латинская Америка", "MX": "Мексика", "FR": "Франция",
    "HANS": "упрощённый", "HANT": "традиционный", "CN": "Китай", "TW": "Тайвань", "HK": "Гонконг",
}


def explain_error(text: str) -> tuple[str, str, str]:
    """Последняя ошибка yt-dlp: (понятное сообщение, подсказка для кнопки, исходный текст)."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    errors = [line for line in lines if line.startswith("ERROR:")]
    raw = errors[-1] if errors else (lines[-1] if lines else "yt-dlp завершился без объяснений.")
    raw = re.sub(r"^ERROR:\s*", "", raw)
    raw = re.sub(r"^\[[\w:]+\]\s*[\w-]*:\s*", "", raw)
    for pattern, message, hint in ERROR_RULES:
        if re.search(pattern, text or "", re.I):
            return message, hint, raw
    return raw[:400], "", raw


def num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def version_age_days(version: str) -> int | None:
    m = re.match(r"(\d{4})\.(\d{2})\.(\d{2})", version or "")
    if not m:
        return None
    try:
        return (date.today() - date(*map(int, m.groups()))).days
    except ValueError:
        return None


def common_args(s: dict) -> list[str]:
    args = []
    if s.get("cookies"):
        args += ["--cookies-from-browser", s["cookies"]]
    if s.get("proxy"):
        args += ["--proxy", s["proxy"]]
    return args


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise ApiError("Вставь ссылку на видео.")
    if re.fullmatch(r"[\w-]{11}", url):
        return f"https://www.youtube.com/watch?v={url}"
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parsed = urlparse(url)
    if not parsed.netloc or " " in url:
        raise ApiError("Это не похоже на ссылку.")
    # Корень канала yt-dlp раскрывает во вкладки, а нужны сами видео.
    if re.search(r"(^|\.)youtube\.com$", parsed.netloc) and re.fullmatch(
        r"/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)/?", parsed.path
    ):
        return f"https://www.youtube.com{parsed.path.rstrip('/')}/videos"
    return url


# ---------------------------------------------------------------- превью

def fmt_size(f: dict, duration) -> int:
    size = f.get("filesize") or f.get("filesize_approx")
    if not size and f.get("tbr") and duration:
        size = f["tbr"] * 125 * duration  # кбит/с в байты
    return int(size or 0)


def quality_label(f: dict) -> int:
    m = re.search(r"(\d{3,4})p", f.get("format_note") or "")
    if m:
        return int(m.group(1))
    w, h = f.get("width"), f.get("height")
    if w and h:
        return min(w, h)
    return h or 0


def codec_family(vcodec: str | None) -> str:
    v = (vcodec or "").lower()
    if v.startswith(("avc", "h264")):
        return "avc"
    if v.startswith("av01"):
        return "av1"
    if v.startswith(("vp9", "vp09")):
        return "vp9"
    return "other"


def pick_thumb(d: dict, min_width: int) -> str | None:
    thumbs = [t for t in (d.get("thumbnails") or []) if t.get("url") and t.get("width")]
    if thumbs:
        big = sorted((t for t in thumbs if t["width"] >= min_width), key=lambda t: t["width"])
        return (big[0] if big else max(thumbs, key=lambda t: t["width"]))["url"]
    if d.get("thumbnail"):
        return d["thumbnail"]
    if (d.get("ie_key") or d.get("extractor_key") or "").startswith("Youtube") and d.get("id"):
        return f"https://i.ytimg.com/vi/{d['id']}/mqdefault.jpg"
    return None


def describe_tracks(raw: list[dict]) -> list[dict]:
    """Звуковые дорожки YouTube: язык, оригинал, дубляж, тифлокомментарий."""
    bases = [t["code"].split("-")[0].lower() for t in raw if not t["code"].lower().endswith("desc")]
    out = []
    for t in raw:
        code, note, pref = t["code"], t["note"], t["pref"]
        base, _, rest = code.partition("-")
        desc = rest.lower() == "desc" or pref <= -10
        name = LANG_NAMES.get(base.lower()) or re.split(r"\s*[(,]", note)[0].strip() or code
        if rest and not desc and bases.count(base.lower()) > 1:
            name += f" ({REGIONS.get(rest.upper(), rest.upper())})"
        if pref >= 10:
            kind = "original"
        elif desc:
            kind = "desc"
        elif re.search(r"dub", note, re.I):
            kind = "dub_auto" if re.search(r"auto", note, re.I) else "dub"
        else:
            kind = ""
        out.append({"code": code, "label": name, "kind": kind, "default": pref == 5, "size": t["size"]})
    rank = {"original": 0, "": 2, "dub": 2, "dub_auto": 3, "desc": 4}
    out.sort(key=lambda t: (rank[t["kind"]] - (1 if t["default"] and t["kind"] != "original" else 0), t["label"]))
    return out


def summarize(d: dict, url: str) -> dict:
    if d.get("_type") == "playlist" or "entries" in d:
        return _summarize_playlist(d, url)

    duration = d.get("duration")
    formats = d.get("formats") or []
    audio_sizes = [fmt_size(f, duration) for f in formats
                   if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")]
    best_audio = max(audio_sizes, default=0)
    groups: dict[int, dict] = {}
    for f in formats:
        # У многих сайтов кодек не указан: тогда видео есть, если известен размер кадра.
        if f.get("vcodec") == "none" or (f.get("vcodec") is None and not f.get("height")):
            continue
        q = quality_label(f)
        if q < 100:
            continue
        size = fmt_size(f, duration)
        if size and f.get("acodec") in (None, "none"):
            size += best_audio
        g = groups.setdefault(q, {"height": q, "fps": 0, "hdr": False, "sizes": {}})
        fam = codec_family(f.get("vcodec"))
        g["sizes"][fam] = max(g["sizes"].get(fam, 0), size)
        g["fps"] = max(g["fps"], int(f.get("fps") or 0))
        if (f.get("dynamic_range") or "SDR") != "SDR":
            g["hdr"] = True
    tracks: dict[str, dict] = {}
    for f in formats:
        if f.get("vcodec") != "none" or f.get("acodec") in (None, "none") or not f.get("language"):
            continue
        t = tracks.setdefault(f["language"], {"code": f["language"], "pref": -100, "note": "", "size": 0})
        pref = f.get("language_preference")
        if pref is not None and pref > t["pref"]:
            t["pref"] = pref
        t["note"] = t["note"] or f.get("format_note") or ""
        t["size"] = max(t["size"], fmt_size(f, duration))
    qualities = []
    for q in sorted(groups, reverse=True):
        g = groups[q]
        sizes = g.pop("sizes")
        biggest = max(sizes.values(), default=0)
        g["size_mp4"] = sizes.get("avc") or biggest
        g["size_mkv"] = sizes.get("av1") or sizes.get("vp9") or biggest
        qualities.append(g)
    return {
        "kind": "video",
        "id": d.get("id"),
        "url": d.get("webpage_url") or url,
        "title": d.get("title") or url,
        "channel": d.get("channel") or d.get("uploader"),
        "duration": duration,
        "thumb": pick_thumb(d, 640),
        "qualities": qualities,
        "audio_size": best_audio,
        "audio_tracks": describe_tracks(list(tracks.values())) if len(tracks) > 1 else [],
        "live": d.get("live_status") == "is_live",
        "has_subs": bool(d.get("subtitles") or d.get("automatic_captions")),
        "site": d.get("extractor_key") or d.get("extractor"),
    }


def _summarize_playlist(d: dict, url: str) -> dict:
    entries, nested = [], 0
    for i, e in enumerate(d.get("entries") or [], 1):
        if not e:
            continue
        if e.get("ie_key") == "YoutubeTab" or e.get("_type") == "playlist":
            nested += 1
            continue
        eurl = e.get("url") or e.get("webpage_url")
        if not eurl:
            continue
        if not eurl.startswith("http") and e.get("ie_key") == "Youtube":
            eurl = f"https://www.youtube.com/watch?v={eurl}"
        entries.append({
            "index": i,
            "id": e.get("id"),
            "url": eurl,
            "title": e.get("title") or eurl,
            "duration": e.get("duration"),
            "channel": e.get("channel") or e.get("uploader"),
            "thumb": pick_thumb(e, 320),
        })
    if not entries:
        if nested:
            raise ApiError("Это подборка плейлистов. Открой нужный плейлист и вставь ссылку на него.")
        raise ApiError("В плейлисте нет доступных видео.")
    return {
        "kind": "playlist",
        "url": d.get("webpage_url") or url,
        "title": d.get("title") or "Плейлист",
        "channel": d.get("channel") or d.get("uploader"),
        "thumb": entries[0]["thumb"],
        "entries": entries,
    }


def fetch_info(tools, url: str, whole_playlist: bool, s: dict) -> dict:
    cmd = [tools.ytdlp, "-J", "--flat-playlist", "--no-colors", *tools.ytdlp_args(), *common_args(s)]
    if not whole_playlist:
        cmd.append("--no-playlist")
    cmd += ["--", url]
    try:
        p = system.run(cmd, timeout=180, env=tools.env())
    except subprocess.TimeoutExpired:
        raise ApiError("yt-dlp три минуты не мог получить данные. Проверь интернет и попробуй ещё раз.")
    except OSError as e:
        raise ApiError(f"Не получилось запустить yt-dlp: {e}", "tools")
    data = None
    lines = (p.stdout or "").strip().splitlines()
    if lines:
        try:
            data = json.loads(lines[-1])
        except ValueError:
            data = None
    if p.returncode != 0 or not data:
        message, hint, raw = explain_error(p.stderr)
        raise ApiError(message, hint, raw)
    return summarize(data, url)


# ---------------------------------------------------------------- загрузка

def safe_name(name: str) -> str:
    name = re.sub(r'[/\\:*?"<>|\x00-\x1f]+', " ", name or "")
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name or "Плейлист")[:120]


def build_cmd(job, s: dict, tools, tmp_root: Path) -> list[str]:
    o = job.opts
    base = TEMPLATES.get(job.template, TEMPLATES["title"])
    if job.group:
        prefix = f"{job.index:03d} - " if job.index else ""
        out = f"{safe_name(job.group).replace('%', '%%')}/{prefix}{base}"
    else:
        out = base
    cmd = [
        tools.ytdlp, "--newline", "--no-colors", "--progress", "--no-playlist", "--no-mtime",
        "--retries", "10", "--fragment-retries", "10", "--concurrent-fragments", "4",
        "--progress-template",
        "download:DL|%(progress.status)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
        "%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s|%(info.format_id)s",
        "--progress-template", "postprocess:PP|%(progress.status)s|%(progress.postprocessor)s",
        "--print", "before_dl:SIZES|%(requested_formats.0.filesize,requested_formats.0.filesize_approx|)s|"
                   "%(requested_formats.1.filesize,requested_formats.1.filesize_approx|)s|"
                   "%(filesize,filesize_approx|)s",
        "--print", "before_dl:TITLE|%(title)s",
        "--print", "after_move:FILE|%(filepath)s",
        "-P", job.folder, "-P", f"temp:{tmp_root / job.id}", "-o", out,
        "--embed-metadata", "--embed-chapters",
        *tools.ytdlp_args(),
    ]
    # Одиночное видео знает точный код дорожки. Для плейлиста это пожелание по языку:
    # en подходит и к en-US, а тифлокомментарий en-desc не подходит.
    lang = o["audio_lang"]
    if not lang:
        lf = ""
    elif job.group:
        lf = f"[language^={lang}][language!$=desc]"
    else:
        lf = f"[language={lang}]"
    if o["mode"] == "audio":
        ext = {"m4a": "[ext=m4a]", "opus": "[acodec=opus]"}.get(o["audio"], "")
        options = ([f"ba{lf}{ext}"] if lf and ext else []) + ([f"ba{lf}"] if lf else [])
        options += ([f"ba{ext}"] if ext else []) + ["ba", "b"]
        # lang первым: без явного выбора берём оригинальную дорожку, а не дубляж.
        cmd += ["-f", "/".join(options), "-S", "lang", "-x", "--audio-quality", "0"]
        if o["audio"] != "best":
            cmd += ["--audio-format", o["audio"]]
    else:
        sort = ["lang"] + ([f"res:{o['quality']}"] if o["quality"] != "best" else [])
        if o["container"] == "mp4":
            # H.264 + AAC открываются везде; выше 1080p YouTube отдаёт только VP9/AV1.
            sort += ["vcodec:h264", "acodec:aac"]
        if lf and o["audio_both"] and o["audio_orig"] and not job.group:
            selector = f"bv*+ba{lf}+ba[language={o['audio_orig']}]/bv*+ba{lf}/bv*+ba/b"
            cmd.append("--audio-multistreams")
        elif lf:
            selector = f"bv*+ba{lf}/bv*+ba/b"
        else:
            selector = "bv*+ba/b"
        # remux нужен для сайтов, которые отдают один готовый файл (avi, flv, webm) без склейки.
        cmd += ["-f", selector, "--merge-output-format", o["container"], "--remux-video", o["container"],
                "-S", ",".join(sort)]
        if o["subs"]:
            cmd += ["--write-subs", "--write-auto-subs", "--sub-langs", s["subs_langs"], "--embed-subs"]
    if o["thumb"]:
        cmd += ["--embed-thumbnail", "--convert-thumbnails", "jpg"]
    if o["sponsor"]:
        cmd += ["--sponsorblock-remove", "sponsor,selfpromo,interaction"]
    if o["start"] or o["end"]:
        cmd += ["--download-sections", f"*{o['start'] or '0'}-{o['end'] or 'inf'}"]
    if job.force:
        cmd.append("--force-overwrites")
    cmd += common_args(s)
    cmd += ["--", job.url]
    return cmd
