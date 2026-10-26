"""
Desktop launcher: starts the local server and shows it in a native window (Edge WebView2 on Windows).
Falls back to the default browser if the native window is unavailable.
"""
from __future__ import annotations

import base64
import logging
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

# A --windowed exe has no console: make print()/logging harmless.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

from werkzeug.serving import make_server

from app import app
from paths import bundle_dir

logging.getLogger("werkzeug").setLevel(logging.ERROR)
TITLE = "Dhivehi PDF Tool"


PREFERRED_PORT = 48731      # fixed so the page keeps the same "origin" and remembers saved signatures between launches


def free_port() -> int:
    for port in (PREFERRED_PORT, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("No free network port")


class Api:
    """Exposed to the page as window.pywebview.api - lets the Download button open a real Save dialog."""

    def save_pdf(self, b64: str, filename: str):
        import webview
        win = webview.windows[0]
        kind = webview.FileDialog.SAVE if hasattr(webview, "FileDialog") else webview.SAVE_DIALOG
        path = win.create_file_dialog(kind, save_filename=filename, file_types=("PDF files (*.pdf)",))
        if not path:
            return None
        path = path if isinstance(path, str) else path[0]
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        with open(path, "wb") as f:
            f.write(base64.b64decode(b64))
        return path


WEBVIEW2_DOWNLOAD = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"


def _log_path() -> Path:
    from paths import app_dir
    return app_dir() / "window_error.log"


def _log_failure(context: str, exc: BaseException) -> None:
    import traceback
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} ({context}) ---\n")
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=f)
    except Exception:
        pass                                                             # logging is best-effort, never fatal


def _is_missing_webview2(exc: BaseException) -> bool:
    text = f"{exc}".lower()
    return any(k in text for k in ("webview2", "edgechromium", "edge chromium", "evergreen", "0x80040154"))


def fallback_browser(url: str, reason: str | None = None) -> None:
    import webbrowser
    import tkinter as tk
    from tkinter import messagebox
    webbrowser.open(url)
    root = tk.Tk(); root.withdraw()
    try:
        root.iconbitmap(str(bundle_dir() / "icon.ico"))
    except Exception:
        pass
    if reason == "webview2":
        msg = (
            "Dhivehi PDF Tool couldn't open its own app window, so it opened in your web browser instead.\n\n"
            "This almost always means the Microsoft Edge WebView2 Runtime isn't installed on this computer "
            "(most Windows 10/11 PCs already have it, but some locked-down office images don't).\n\n"
            "To get the real app window next time, install it from:\n"
            f"{WEBVIEW2_DOWNLOAD}\n"
            "(search \"WebView2 Runtime\" if that link doesn't open) - then restart DhivehiPDF.exe.\n\n"
            "You can keep using the tool in the browser for now - everything works the same way.\n\n"
            "Click OK (or close this box) to quit the tool."
        )
    else:
        detail = f"\n\nDetails were saved to:\n{_log_path()}" if reason else ""
        msg = (
            "Dhivehi PDF Tool couldn't open its own app window, so it opened in your web browser instead. "
            "Everything works the same way there." + detail +
            "\n\nClick OK (or close this box) to quit the tool."
        )
    messagebox.showinfo(TITLE, msg)


def main() -> None:
    port = free_port()
    server = make_server("127.0.0.1", port, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    for _ in range(50):                      # wait until the server answers
        try:
            urllib.request.urlopen(url, timeout=0.5); break
        except Exception:
            time.sleep(0.1)

    reason = None
    try:
        import webview
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.create_window(TITLE, url, js_api=Api(), width=1360, height=900, min_size=(960, 640))
        data_dir = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "DhivehiPDF"
        data_dir.mkdir(parents=True, exist_ok=True)
        opts = dict(private_mode=False, storage_path=str(data_dir))      # keeps saved signatures
        icon = bundle_dir() / "icon.ico"
        if icon.exists():
            opts["icon"] = str(icon)
        # On Windows, ask pywebview for the Edge WebView2 backend explicitly instead of letting it pick
        # silently - that way a missing WebView2 Runtime raises a clear error here instead of pywebview
        # quietly trying (and failing) something else first.
        if sys.platform == "win32":
            opts["gui"] = "edgechromium"
        try:
            webview.start(**opts)
        except TypeError:                                                # older pywebview without icon/gui support
            opts.pop("icon", None); opts.pop("gui", None)
            webview.start(**opts)
    except Exception as exc:
        _log_failure("webview.start", exc)
        reason = "webview2" if _is_missing_webview2(exc) else "error"
        fallback_browser(url, reason)
    server.shutdown()


if __name__ == "__main__":
    main()
