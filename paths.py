"""Where things live, both when run from source and when frozen by PyInstaller."""
import sys
from pathlib import Path


def bundle_dir() -> Path:
    """Read-only resources (fonts, static page). PyInstaller unpacks them to _MEIPASS."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def app_dir() -> Path:
    """Folder next to the .exe (or the source folder). Editable things like templates live here."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent
