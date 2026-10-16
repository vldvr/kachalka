"""Скачивание компонентов: какие файлы берём под каждую систему и как распаковываем. Сеть не нужна."""
import io
import tarfile
import zipfile

import pytest

from kachalka import system, tools


@pytest.mark.parametrize("platform, arm, expected", [
    ("win", False, ["yt-dlp.exe", "ffmpeg-master-latest-win64-gpl-shared.zip", "deno-x86_64-pc-windows-msvc.zip"]),
    ("mac", True, ["yt-dlp_macos", "macos/arm64/release/ffmpeg.zip", "deno-aarch64-apple-darwin.zip"]),
    ("mac", False, ["yt-dlp_macos", "macos/amd64/release/ffmpeg.zip", "deno-x86_64-apple-darwin.zip"]),
    ("linux", False, ["yt-dlp_linux", "ffmpeg-master-latest-linux64-gpl.tar.xz", "deno-x86_64-unknown-linux-gnu.zip"]),
])
def test_packages_per_platform(monkeypatch, platform, arm, expected):
    monkeypatch.setattr(system, "IS_WIN", platform == "win")
    monkeypatch.setattr(system, "IS_MAC", platform == "mac")
    monkeypatch.setattr(tools, "_arm", lambda: arm)
    urls = [pkg.urls[0] for name in ("yt-dlp", "ffmpeg", "deno") for pkg in tools.packages(name)]
    for fragment in expected:
        assert any(url.endswith(fragment) for url in urls), (fragment, urls)
    if platform == "mac":
        # У ffmpeg для macOS две программы и запасное зеркало со свежей сборкой.
        ffmpeg = tools.packages("ffmpeg")
        assert len(ffmpeg) == 2 and all(len(p.urls) == 2 and "snapshot" in p.urls[1] for p in ffmpeg)


def test_extract_zip_picks_needed_files(tmp_path):
    archive = tmp_path / "ffmpeg.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("ffmpeg-build/bin/ffmpeg.exe", b"ff")
        zf.writestr("ffmpeg-build/bin/ffprobe.exe", b"fp")
        zf.writestr("ffmpeg-build/bin/avcodec-62.dll", b"dll")
        zf.writestr("ffmpeg-build/doc/readme.txt", b"skip")
    out = tmp_path / "out"
    out.mkdir()
    pkg = tools.Package(["x"], {"ffmpeg.exe": "", "ffprobe.exe": "", "*.dll": ""}, "zip")
    tools._extract(pkg, archive, out)
    assert sorted(p.name for p in out.iterdir()) == ["avcodec-62.dll", "ffmpeg.exe", "ffprobe.exe"]


def test_extract_tar_and_missing_file(tmp_path):
    archive = tmp_path / "ffmpeg.tar.xz"
    with tarfile.open(archive, "w:xz") as tf:
        data = b"binary"
        info = tarfile.TarInfo("ffmpeg-build/bin/ffmpeg")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    out = tmp_path / "out"
    out.mkdir()
    pkg = tools.Package(["x"], {"ffmpeg": "", "ffprobe": ""}, "tar")
    with pytest.raises(tools.ToolError, match="ffprobe"):
        tools._extract(pkg, archive, out)


def test_raw_download_is_renamed(tmp_path):
    archive = tmp_path / "download.part"
    archive.write_bytes(b"#!/bin/sh\n")
    pkg = tools.Package(["x"], {"yt-dlp_macos": "yt-dlp"}, "raw")
    tools._extract(pkg, archive, tmp_path)
    assert (tmp_path / "yt-dlp").read_bytes() == b"#!/bin/sh\n"


def test_tools_prefer_own_copy(tmp_path):
    paths = system.Paths(tmp_path)
    paths.ensure()
    own = paths.bin / tools.Tools.exe("yt-dlp")
    own.write_text("")
    t = tools.Tools(paths, use_system=False)
    assert t.state["yt-dlp"]["source"] == "own"
    assert t.state["ffmpeg"]["status"] == "missing"
    assert not t.ready
