"""Настройки и параметры загрузки, которые приходят из окна."""
from __future__ import annotations

import copy
import os
import re

from . import system


class ApiError(Exception):
    """Ошибка, которую можно показать человеку как есть."""

    def __init__(self, message: str, hint: str = "", raw: str = "", status: int = 400):
        super().__init__(message)
        self.message, self.hint, self.raw, self.status = message, hint, raw, status


TEMPLATES = {
    "title": "%(title)s.%(ext)s",
    "title_id": "%(title)s [%(id)s].%(ext)s",
    "channel_title": "%(channel,uploader|Без канала)s - %(title)s.%(ext)s",
    "date_title": "%(upload_date>%Y-%m-%d|0000-00-00)s %(title)s.%(ext)s",
}
BROWSERS = ["", "chrome", "safari", "firefox", "brave", "edge", "opera", "vivaldi", "chromium"]
QUALITIES = ["best", "4320", "2160", "1440", "1080", "720", "480", "360", "240", "144"]
AUDIO_FORMATS = ["mp3", "m4a", "opus", "best"]
LANG_RE = re.compile(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8}){0,3}")
TIME_RE = re.compile(r"\d{1,3}(:\d{1,2}){0,2}(\.\d+)?")

DEFAULT_OPTS = {
    "mode": "video",
    "quality": "1080",
    "container": "mp4",
    "audio": "mp3",
    "subs": False,
    "thumb": True,
    "sponsor": False,
    "start": "",
    "end": "",
    "audio_lang": "",   # код дорожки; пусто значит оригинал
    "audio_orig": "",   # код оригинальной дорожки, нужен для «оригинал второй дорожкой»
    "audio_both": False,
    "audio_label": "",  # название дорожки для строки в очереди
}


def default_settings() -> dict:
    return {
        "folder": str(system.downloads_dir() / "YouTube"),
        "template": "title",
        "cookies": "",
        "proxy": "",
        "parallel": 2,
        "subs_langs": "ru.*,en.*",
        "last": dict(DEFAULT_OPTS),
    }


def clean_opts(raw) -> dict:
    """Проверяет параметры загрузки из окна: всё неизвестное заменяется значением по умолчанию."""
    raw = raw if isinstance(raw, dict) else {}
    o = dict(DEFAULT_OPTS)
    if raw.get("mode") in ("video", "audio"):
        o["mode"] = raw["mode"]
    if str(raw.get("quality")) in QUALITIES:
        o["quality"] = str(raw["quality"])
    if raw.get("container") in ("mp4", "mkv"):
        o["container"] = raw["container"]
    if raw.get("audio") in AUDIO_FORMATS:
        o["audio"] = raw["audio"]
    for key in ("subs", "thumb", "sponsor"):
        if key in raw:
            o[key] = bool(raw[key])
    for key in ("start", "end"):
        value = str(raw.get(key) or "").strip()
        if value and not TIME_RE.fullmatch(value):
            raise ApiError("Время отрезка пишется так: 1:30 или 1:02:15.")
        o[key] = value
    for key in ("audio_lang", "audio_orig"):
        value = str(raw.get(key) or "").strip()
        if value and not LANG_RE.fullmatch(value):
            raise ApiError("Не понял, какую звуковую дорожку скачивать.")
        o[key] = value
    o["audio_both"] = bool(raw.get("audio_both")) and bool(o["audio_lang"]) and o["audio_lang"] != o["audio_orig"]
    o["audio_label"] = re.sub(r"[\x00-\x1f]", "", str(raw.get("audio_label") or ""))[:40]
    return o


class Settings:
    def __init__(self, paths: system.Paths):
        self.paths = paths
        defaults = default_settings()
        stored = system.load_json(paths.settings, {})
        self.data = {**defaults, **{k: v for k, v in stored.items() if k in defaults}}
        try:
            self.data["last"] = clean_opts({**DEFAULT_OPTS, **(stored.get("last") or {})})
        except ApiError:
            self.data["last"] = dict(DEFAULT_OPTS)

    def get(self) -> dict:
        return copy.deepcopy(self.data)

    def update(self, patch: dict) -> dict:
        d = self.data
        if "folder" in patch:
            folder = os.path.expanduser(str(patch["folder"]).strip())
            if not folder or not os.path.isabs(folder):
                raise ApiError("Укажи полный путь к папке, например " + str(system.downloads_dir() / "YouTube"))
            d["folder"] = folder
        if patch.get("template") in TEMPLATES:
            d["template"] = patch["template"]
        if "cookies" in patch:
            if patch["cookies"] not in BROWSERS:
                raise ApiError("Такой браузер не поддерживается.")
            d["cookies"] = patch["cookies"]
        if "proxy" in patch:
            proxy = str(patch["proxy"]).strip()
            if proxy and not re.match(r"^(https?|socks4a?|socks5h?)://\S+$", proxy):
                raise ApiError("Прокси пишется так: socks5://127.0.0.1:1080 или http://host:port.")
            d["proxy"] = proxy
        if "parallel" in patch:
            d["parallel"] = max(1, min(4, int(patch["parallel"])))
        if "subs_langs" in patch:
            langs = str(patch["subs_langs"]).strip()
            if not re.fullmatch(r"[\w.*,\-]+", langs or "x"):
                raise ApiError("Языки субтитров пишутся через запятую, например ru.*,en.*")
            d["subs_langs"] = langs or default_settings()["subs_langs"]
        if "last" in patch:
            d["last"] = clean_opts(patch["last"])
        system.save_json(self.paths.settings, d)
        return self.get()
