# -*- mode: python -*-
# Сборка Качалки PyInstaller-ом для macOS и Windows:
#   pyinstaller packaging/kachalka.spec --noconfirm --clean
# На выходе dist/Kachalka (Windows) или dist/Качалка.app (macOS).
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from kachalka import __version__  # noqa: E402

ICONS = ROOT / "packaging" / "icons"
IS_MAC = sys.platform == "darwin"

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "kachalka" / "web"), "kachalka/web")],
    excludes=["tkinter", "unittest", "pydoc", "test"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Kachalka",
    console=False,
    icon=str(ICONS / ("AppIcon.icns" if IS_MAC else "kachalka.ico")),
)
coll = COLLECT(exe, a.binaries, a.datas, name="Kachalka")

if IS_MAC:
    app = BUNDLE(
        coll,
        name="Качалка.app",
        icon=str(ICONS / "AppIcon.icns"),
        bundle_identifier="io.github.vldvr.kachalka",
        version=__version__,
        info_plist={
            "CFBundleName": "Качалка",
            "CFBundleDisplayName": "Качалка",
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "LSApplicationCategoryType": "public.app-category.utilities",
            "LSMinimumSystemVersion": "12.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
        },
    )
