"""
Dhivehi PDF Tool - local web app.

    python app.py        then open http://127.0.0.1:5000

Uploaded PDFs are kept in a temp folder for a few hours and never leave your computer.
"""
from __future__ import annotations

import json
import re
import tempfile
import time
import uuid
from pathlib import Path

import pymupdf
from flask import Flask, Response, abort, jsonify, request, send_from_directory

import pdf_core as core
from paths import bundle_dir
from version import APP_NAME, APP_RELEASED, APP_VERSION

BASE = bundle_dir()
UPLOADS = Path(tempfile.gettempdir()) / "dhivehi_pdf_tool"
UPLOADS.mkdir(exist_ok=True)
KEEP_SECONDS = 6 * 3600

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB


# ---------------------------------------------------------------- helpers
def _cleanup() -> None:
    cutoff = time.time() - KEEP_SECONDS
    for f in UPLOADS.glob("*.pdf"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


_cleanup()      # remove old working copies left from earlier sessions


def _load(pid: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{32}", pid):
        abort(404)
    f = UPLOADS / f"{pid}.pdf"
    if not f.exists():
        abort(404, "That PDF has expired - please upload it again.")
    return f.read_bytes()


def _pdf_response(data: bytes, warnings: list[str] | None = None, name: str = "output.pdf", info: list[str] | None = None) -> Response:
    resp = Response(data, mimetype="application/pdf")
    resp.headers["Content-Disposition"] = f'inline; filename="{name}"'
    # Headers must be ASCII, so JSON-escape the messages.
    resp.headers["X-Warnings"] = json.dumps(warnings or [], ensure_ascii=True)
    resp.headers["X-Info"] = json.dumps(info or [], ensure_ascii=True)     # friendly (non-warning) messages
    resp.headers["Access-Control-Expose-Headers"] = "X-Warnings, X-Info"
    return resp


# ---------------------------------------------------------------- pages & assets
@app.get("/")
def index():
    return send_from_directory(BASE / "static", "index.html")


@app.get("/api/about")
def about():
    return jsonify(name=APP_NAME, version=APP_VERSION, released=APP_RELEASED)


@app.get("/icon.png")
@app.get("/favicon.ico")
def icon():
    return send_from_directory(BASE / "static", "icon.png", mimetype="image/png")


@app.get("/fonts/<path:name>")
def fonts(name: str):
    return send_from_directory(core.FONT_DIR, name)


@app.get("/api/fonts")
def fonts_list():
    return jsonify(fonts=core.list_fonts(refresh=request.args.get("refresh") == "1"))


@app.get("/api/fontfile")
def fontfile():
    """Serve a listed font to the page so the on-screen preview uses the same typeface."""
    fid = request.args.get("id", "")
    if fid not in {f["id"] for f in core.list_fonts()}:
        abort(404)
    return Response(core.font_path(fid).read_bytes(), mimetype="font/ttf", headers={"Cache-Control": "max-age=3600"})


@app.post("/api/fonts")
def fonts_add():
    f = request.files.get("file")
    if not f:
        return jsonify(error="No file received"), 400
    try:
        return jsonify(font=core.add_font(f.filename or "font.ttf", f.read()))
    except ValueError as e:
        return jsonify(error=str(e)), 400


# ---------------------------------------------------------------- upload / preview
@app.post("/api/upload")
def upload():
    _cleanup()
    f = request.files.get("file")
    if not f:
        return jsonify(error="No file received"), 400
    data = f.read()
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        return jsonify(error="That does not look like a valid PDF."), 400
    if doc.needs_pass:
        return jsonify(error="This PDF is password-protected. Remove the password first."), 400
    pid = uuid.uuid4().hex
    (UPLOADS / f"{pid}.pdf").write_bytes(data)
    return jsonify(
        id=pid,
        name=f.filename,
        size=len(data),
        pages=[{"w": p.rect.width, "h": p.rect.height} for p in doc],
        field_count=len(core.list_fields(doc)),
    )


@app.get("/api/page/<pid>/<int:n>.png")
def page_png(pid: str, n: int):
    doc = pymupdf.open(stream=_load(pid), filetype="pdf")
    if not 0 <= n < len(doc):
        abort(404)
    zoom = min(max(float(request.args.get("zoom", 1.5)), 0.5), 4)
    png = doc[n].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")
    return Response(png, mimetype="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/preview")
def preview():
    """Render an already-built PDF to PNG data-URIs (used by the desktop window, which has no built-in PDF viewer to rely on)."""
    import base64
    try:
        doc = pymupdf.open(stream=request.get_data(), filetype="pdf")
    except Exception:
        return jsonify(error="Could not read the PDF"), 400
    m = pymupdf.Matrix(1.4, 1.4)
    pages = ["data:image/png;base64," + base64.b64encode(pg.get_pixmap(matrix=m).tobytes("png")).decode() for pg in list(doc)[:30]]
    return jsonify(pages=pages, total=len(doc))


# ---------------------------------------------------------------- 1. overlay
@app.post("/api/overlay/<pid>")
def overlay(pid: str):
    items = (request.get_json(silent=True) or {}).get("items", [])
    try:
        data, warnings = core.apply_items(_load(pid), items)
    except Exception as e:  # surface a readable message in the UI
        return jsonify(error=str(e)), 400
    return _pdf_response(data, warnings, "overlay.pdf")


@app.get("/api/stamps")
def stamps():
    return jsonify(stamps=core.list_stamps())


# ---------------------------------------------------------------- compress
def _mb(n: int) -> str:
    return f"{n / 1_000_000:.2f} MB" if n >= 100_000 else f"{n / 1000:.0f} KB"


@app.post("/api/compress/<pid>")
def compress(pid: str):
    body = request.get_json(silent=True) or {}
    src = _load(pid)
    target = body.get("target_bytes")
    try:
        target = int(target) if target else None
    except (TypeError, ValueError):
        target = None
    try:
        data, info = core.compress_pdf(
            src, body.get("level", "balanced"), bool(body.get("grayscale")), bool(body.get("strip_metadata")),
            target_bytes=target,
        )
    except Exception as e:
        return jsonify(error=str(e)), 400
    msgs = [f"Size: {_mb(info['original'])} \u2192 {_mb(info['new'])}" + (f" ({info['saved_pct']}% smaller)" if info["new"] < info["original"] else "")]
    if target:
        msgs.append(f"Target was {_mb(target)} \u2014 {'reached.' if info.get('target_met') else 'not reached (see below).'}")
    return _pdf_response(data, info["notes"], "compressed.pdf", info=msgs)


# ---------------------------------------------------------------- 2. forms
@app.get("/api/fields/<pid>")
def fields(pid: str):
    return jsonify(fields=core.list_fields(_load(pid)))


@app.post("/api/fill/<pid>")
def fill(pid: str):
    body = request.get_json(silent=True) or {}
    try:
        data, warnings = core.fill_form(
            _load(pid),
            body.get("values", {}),
            flatten=bool(body.get("flatten")),
            font_size=body.get("font_size") or None,
            font=body.get("font"),
        )
    except Exception as e:
        return jsonify(error=str(e)), 400
    return _pdf_response(data, warnings, "filled.pdf")


# ---------------------------------------------------------------- 3. templates
@app.get("/api/templates")
def templates():
    return jsonify(templates=core.list_templates())


@app.post("/api/generate/<tpl>")
def generate(tpl: str):
    body = request.get_json(silent=True) or {}
    try:
        data = core.generate_pdf(tpl, body.get("values", {}), page_numbers=bool(body.get("page_numbers")), font=body.get("font"))
    except Exception as e:
        return jsonify(error=str(e)), 400
    return _pdf_response(data, [], f"{tpl}.pdf")


if __name__ == "__main__":
    # 127.0.0.1 = only this computer can reach it.
    app.run(host="127.0.0.1", port=5000, debug=False)
