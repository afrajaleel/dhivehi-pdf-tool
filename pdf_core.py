"""
pdf_core.py - Dhivehi (Thaana) PDF helpers built on PyMuPDF.

Three things, all with correct right-to-left shaping (HarfBuzz via MuPDF):

    overlay_text()   put text boxes on an existing PDF
    fill_form()      fill AcroForm fields (Thaana values are drawn as text, not widget values)
    generate_pdf()   render an HTML/Jinja template to a multi-page PDF

Every function takes PDF *bytes* (or a path) and returns PDF *bytes*, so it is
easy to call from a web app, a script, or a notebook.
"""
from __future__ import annotations

import hashlib
import html as _html
import io
import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import pymupdf
from jinja2 import Environment, FileSystemLoader, meta, select_autoescape
from markupsafe import Markup, escape

from paths import app_dir, bundle_dir

FONT_DIR = bundle_dir() / "fonts"
# Templates next to the .exe win (so users can add their own); otherwise use the bundled copy.
TEMPLATE_DIR = app_dir() / "pdf_templates"
if not TEMPLATE_DIR.exists():
    TEMPLATE_DIR = bundle_dir() / "pdf_templates"

USER_FONT_DIR = app_dir() / "fonts"          # fonts the user adds live here (next to the .exe when packaged)
DEFAULT_FONT = "f:NotoSansThaana-Regular.ttf"


# --------------------------------------------------------------------------
# Fonts: bundled + user-added + Thaana-capable fonts installed on the computer
# --------------------------------------------------------------------------
_FONT_EXT = {".ttf", ".otf"}
_SKIP_WORDS = ("bold", "italic", "oblique", "black", "light", "thin", "medium", "semibold", "condensed")
_font_index: dict[str, dict] | None = None


def _system_font_dirs() -> list[Path]:
    home = Path.home()
    if sys.platform == "win32":
        win = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        local = Path(os.environ.get("LOCALAPPDATA", str(home))) / "Microsoft" / "Windows" / "Fonts"
        return [win, local]
    if sys.platform == "darwin":
        return [Path("/Library/Fonts"), Path("/System/Library/Fonts"), home / "Library" / "Fonts"]
    return [Path("/usr/share/fonts"), home / ".local" / "share" / "fonts", home / ".fonts"]


def _has_thaana_glyphs(font: pymupdf.Font) -> bool:
    return bool(font.has_glyph(0x0780)) and bool(font.has_glyph(0x07A6))


def _pretty(name: str) -> str:
    name = re.sub(r"[-_]+", " ", name)
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    return re.sub(r"\s+(Regular|Roman|Book)$", "", name.strip(), flags=re.I)


def list_fonts(refresh: bool = False) -> list[dict]:
    """[{id, name, source, default}] - the default first, then bundled/added, then system fonts."""
    global _font_index
    if _font_index is None or refresh:
        idx: dict[str, dict] = {}
        seen: set[str] = set()

        def add(path: Path, fid: str, source: str, check: bool) -> None:
            key = str(path.resolve()).lower()
            if key in seen:
                return
            try:
                f = pymupdf.Font(fontfile=str(path))
                if check and not _has_thaana_glyphs(f):
                    return
                if check and any(w in path.stem.lower() for w in _SKIP_WORDS):
                    return  # bold/italic variants are picked up automatically from the regular file
                seen.add(key)
                idx[fid] = {"id": fid, "name": _pretty(path.stem), "source": source, "path": str(path)}
            except Exception:
                pass

        for d, src in ((FONT_DIR, "bundled"), (USER_FONT_DIR, "added")):
            if d.exists():
                for p in sorted(d.iterdir()):
                    if p.suffix.lower() in _FONT_EXT and not any(w in p.stem.lower() for w in _SKIP_WORDS):
                        add(p, f"f:{p.name}", src, check=True)
        for d in _system_font_dirs():
            if d.exists():
                for p in sorted(d.rglob("*")):
                    if p.suffix.lower() in _FONT_EXT:
                        add(p, "s:" + hashlib.sha1(str(p).lower().encode()).hexdigest()[:10], "system", check=True)
        _font_index = idx
        _font_setup.cache_clear()
    out = list(_font_index.values())
    out.sort(key=lambda f: (f["id"] != DEFAULT_FONT, {"bundled": 0, "added": 1, "system": 2}[f["source"]], f["name"].lower()))
    return [{**{k: v for k, v in f.items() if k != "path"}, "default": f["id"] == DEFAULT_FONT} for f in out]


def font_path(font_id: str | None) -> Path:
    list_fonts()
    info = (_font_index or {}).get(font_id or "") or (_font_index or {}).get(DEFAULT_FONT)
    if not info:
        raise RuntimeError("No Thaana font found - put a .ttf in the fonts folder.")
    return Path(info["path"])


def _bold_sibling(p: Path) -> Path | None:
    stem = p.stem
    cands = [stem.replace("Regular", "Bold"), stem + "-Bold", stem + "Bold", stem + "bd", stem + "b", stem + "-bold"]
    for s in cands:
        if s != stem:
            for ext in (p.suffix, p.suffix.upper(), ".ttf", ".otf"):
                q = p.with_name(s + ext)
                if q.exists():
                    return q
    return None


@lru_cache(maxsize=16)
def _font_setup(font_id: str | None) -> tuple[str, pymupdf.Archive]:
    """CSS @font-face rules + an Archive that lets the HTML engine find the font bytes."""
    reg = font_path(font_id)
    bold = _bold_sibling(reg) or reg
    arch = pymupdf.Archive()
    arch.add(reg.read_bytes(), "dv-regular" + reg.suffix.lower())
    arch.add(bold.read_bytes(), "dv-bold" + bold.suffix.lower())
    css = (
        f"@font-face {{ font-family: Thaana; src: url(dv-regular{reg.suffix.lower()}); }}\n"
        f"@font-face {{ font-family: Thaana; font-weight: bold; src: url(dv-bold{bold.suffix.lower()}); }}\n"
        ".dvr { font-family: Thaana, sans-serif; }\n"
    )
    return css, arch


def add_font(filename: str, data: bytes) -> dict:
    """Validate an uploaded font (must contain Thaana) and store it in the user font folder."""
    ext = Path(filename).suffix.lower()
    if ext not in _FONT_EXT:
        raise ValueError("Please choose a .ttf or .otf font file.")
    try:
        f = pymupdf.Font(fontbuffer=data)
    except Exception:
        raise ValueError("That file could not be read as a font.")
    if not _has_thaana_glyphs(f):
        raise ValueError("That font has no Thaana letters, so it can't be used for Dhivehi.")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name)
    USER_FONT_DIR.mkdir(parents=True, exist_ok=True)
    (USER_FONT_DIR / safe).write_bytes(data)
    list_fonts(refresh=True)
    return next(x for x in list_fonts() if x["id"] == f"f:{safe}")


STORY_CSS = """
body { font-family: Helvetica, sans-serif; font-size: 12pt; line-height: 1.5; }
h1 { font-size: 20pt; margin: 0 0 10pt 0; }
h2 { font-size: 16pt; margin: 0 0 8pt 0; }
p  { margin: 0 0 8pt 0; }
/* Thaana glyphs are drawn small for their point size, so paragraphs containing it get a boost. */
p.dv  { font-size: 15pt; line-height: 1.7; }
h1.dv { font-size: 26pt; }
h2.dv { font-size: 21pt; }
"""


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def has_thaana(text: str) -> bool:
    """True if the text contains any Thaana character (U+0780-U+07BF)."""
    return any(0x0780 <= ord(c) <= 0x07BF for c in str(text))


def direction(text: str) -> str:
    """'rtl' or 'ltr' from the first strongly-directional character."""
    for c in str(text):
        o = ord(c)
        if 0x0780 <= o <= 0x07BF or 0x0590 <= o <= 0x08FF:
            return "rtl"
        if c.isalpha():
            return "ltr"
    return "ltr"


# Thaana letters/fili plus the Arabic-script punctuation Dhivehi uses.
_TH = "\u0780-\u07BF\u060C\u061B\u061F"
_TH_RUN = re.compile(rf"[{_TH}](?:[{_TH}\s]*[{_TH}])?")


def wrap_thaana(html: str) -> str:
    """
    Wrap every run of Thaana text in <span class="dvr"> so it is drawn with the *chosen* Thaana font.

    (If the font were simply listed in font-family, MuPDF would draw Thaana with its own built-in
    fallback font and ignore the selection. Latin text keeps the normal sans-serif font.)
    """
    return _TH_RUN.sub(lambda m: f'<span class="dvr">{m.group(0)}</span>', html)


LRM = "\u200e"


def fix_numbers(text: str) -> str:
    """
    Put an invisible left-to-right mark before every run of digits.

    Without it, a number that follows Thaana text (e.g. "ތާރީޚް: 19 September 2026") is treated as an
    Arabic-style number by the Unicode bidi algorithm and the words after it get shuffled.
    """
    return re.sub(r"(?<![\d\u200e])(?=\d)", LRM, str(text))


def _open(pdf: bytes | str | Path) -> pymupdf.Document:
    if isinstance(pdf, (bytes, bytearray)):
        return pymupdf.open(stream=bytes(pdf), filetype="pdf")
    return pymupdf.open(str(pdf))


def _to_bytes(doc: pymupdf.Document) -> bytes:
    return doc.tobytes(garbage=3, deflate=True)


def _text_html(text: str, size: float, color: str, align: str, bold: bool) -> str:
    """Build the little HTML snippet that insert_htmlbox draws."""
    d = direction(text)
    if has_thaana(text):
        text = fix_numbers(text)
    body = wrap_thaana(_html.escape(str(text))).replace("\r\n", "\n").replace("\n", "<br>")
    css = (
        f"font-family:Helvetica,sans-serif;font-size:{size}pt;color:{color};"
        f"line-height:1.3;margin:0;"
    )
    if bold:
        css += "font-weight:bold;"
    # "auto" = start of the line (right for Dhivehi, left for English), so no rule is needed.
    # Note: MuPDF treats left/right as start/end inside a right-to-left block, so swap them there.
    if align in ("left", "right") and d == "rtl":
        align = "right" if align == "left" else "left"
    if align in ("left", "center", "right"):
        css += f"text-align:{align};"
    return f'<div dir="{d}" style="{css}">{body}</div>'


def _draw_text(
    page: pymupdf.Page,
    rect: pymupdf.Rect,
    text: str,
    size: float = 12,
    color: str = "#000000",
    align: str = "auto",
    bold: bool = False,
    shrink: bool = True,
    font: str | None = None,
) -> float:
    """Draw text in rect (in the page's *displayed* coordinates). Returns the scale used (1 = no shrink, <0 = didn't fit)."""
    if not str(text).strip():
        return 1.0
    rect = pymupdf.Rect(rect)
    rotate = 0
    if page.rotation:
        # Callers give coordinates as seen on screen; convert to the page's raw space.
        rect = (rect * page.derotation_matrix).normalize()
        rotate = page.rotation
    font_css, archive = _font_setup(font)
    spare, scale = page.insert_htmlbox(
        rect,
        _text_html(text, size, color, align, bold),
        css=font_css,
        archive=archive,
        scale_low=0 if shrink else 1,
        rotate=rotate,
    )
    return scale if spare >= 0 else -1.0


# --------------------------------------------------------------------------
# 1. Add things to an existing PDF: text, images (signatures / logos), stamps
# --------------------------------------------------------------------------
def _rgb(color: str) -> tuple[float, float, float]:
    h = (color or "#000000").lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    try:
        return tuple(int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (0.0, 0.0, 0.0)


def _raw(page: pymupdf.Page, rect: pymupdf.Rect) -> tuple[pymupdf.Rect, int]:
    """Displayed coordinates -> the page's raw coordinates (matters for pages with a /Rotate)."""
    if page.rotation:
        return (rect * page.derotation_matrix).normalize(), page.rotation
    return rect, 0


def _pages_for(it: dict, n: int) -> list[int]:
    """Which pages an item goes on: 'this' (default), 'all', 'first', 'last', or a range like '1-3,5' (1-based)."""
    spec = str(it.get("pages") or "this").strip().lower()
    if spec in ("this", ""):
        return [int(it.get("page", 0))]
    if spec == "all":
        return list(range(n))
    if spec == "first":
        return [0]
    if spec == "last":
        return [n - 1]
    out: list[int] = []
    for part in spec.replace(" ", "").split(","):
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        out += [p - 1 for p in range(min(a, b), max(a, b) + 1) if 1 <= p <= n]
    return sorted(set(out))


def _place_rotated(page: pymupdf.Page, rect: pymupdf.Rect, src: pymupdf.Document, angle: float) -> None:
    """Place a one-page PDF (src) in rect, rotated `angle` degrees clockwise about the centre, without shrinking it."""
    from math import cos, sin, radians
    a = radians(abs(angle))
    bw = rect.width * abs(cos(a)) + rect.height * abs(sin(a))
    bh = rect.width * abs(sin(a)) + rect.height * abs(cos(a))
    cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
    big = pymupdf.Rect(cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2)
    r, rot = _raw(page, big)
    page.show_pdf_page(r, src, 0, rotate=-angle + rot, keep_proportion=True, overlay=True)


def _draw_image(page: pymupdf.Page, rect: pymupdf.Rect, data: bytes, angle: float = 0.0) -> None:
    if not angle:
        r, rot = _raw(page, rect)
        page.insert_image(r, stream=data, keep_proportion=True, rotate=rot, overlay=True)
        return
    src = pymupdf.open()
    pg = src.new_page(width=rect.width, height=rect.height)
    pg.insert_image(pymupdf.Rect(0, 0, rect.width, rect.height), stream=data, keep_proportion=True)
    _place_rotated(page, rect, src, angle)


def _stamp_source(text: str, w: float, h: float, color: str, border: bool, date_text: str, font: str | None) -> pymupdf.Document:
    """A tiny one-page PDF containing the stamp, so it can be placed (and rotated) as vector art."""
    font_css, archive = _font_setup(font)
    col = _rgb(color)
    src = pymupdf.open()
    pg = src.new_page(width=w, height=h)
    if border:
        lw = max(1.2, min(w, h) * 0.045)
        inset = lw / 2 + 0.5
        pg.draw_rect(pymupdf.Rect(inset, inset, w - inset, h - inset), color=col, width=lw, radius=0.18)
        px, py = w * 0.09, h * 0.12
    else:
        px, py = w * 0.02, h * 0.05
    inner = pymupdf.Rect(px, py, w - px, h - py)
    hexcol = "#%02x%02x%02x" % tuple(round(v * 255) for v in col)
    size = inner.height * (0.8 if not date_text else 0.62)
    body = wrap_thaana(_html.escape(fix_numbers(text) if has_thaana(text) else text)).replace("\n", "<br>")
    html = (
        f'<div dir="{direction(text)}" style="font-family:Helvetica,sans-serif;font-weight:bold;text-align:center;'
        f'font-size:{size}pt;line-height:1.15;color:{hexcol};margin:0">{body}</div>'
    )
    if date_text:
        date_body = wrap_thaana(_html.escape(fix_numbers(date_text) if has_thaana(date_text) else date_text))
        html += (
            f'<div dir="{direction(date_text)}" style="font-family:Helvetica,sans-serif;text-align:center;font-size:{size * 0.42}pt;'
            f'line-height:1.2;color:{hexcol};margin:0">{date_body}</div>'
        )
    # First pass on a scratch page tells us how much room is left, so the stamp text can be centred vertically.
    scratch = pymupdf.open().new_page(width=w, height=h)
    spare, _ = scratch.insert_htmlbox(inner, html, css=font_css, archive=archive, scale_low=0)
    if spare > 0:
        inner.y0 += spare / 2
    pg.insert_htmlbox(inner, html, css=font_css, archive=archive, scale_low=0)
    return src


def _draw_stamp(page: pymupdf.Page, rect: pymupdf.Rect, it: dict) -> None:
    text = str(it.get("text", ""))
    angle = float(it.get("angle", 0) or 0)          # degrees, clockwise (as on screen)
    src = _stamp_source(text, rect.width, rect.height, it.get("color", "#b91c1c"), bool(it.get("border", True)),
                        str(it.get("date_text", "") or ""), it.get("font"))
    _place_rotated(page, rect, src, angle)


def _decode_data_url(s: str) -> bytes:
    import base64
    return base64.b64decode(s.split(",", 1)[1] if "," in s else s)


def apply_items(pdf: bytes | str | Path, items: Iterable[dict]) -> tuple[bytes, list[str]]:
    """
    Add text, images and stamps to a PDF. Every item is a dict with
        kind    'text' (default) | 'image' | 'stamp'
        page    0-based page index the item was placed on
        pages   where to put it: 'this' (default) | 'all' | 'first' | 'last' | '1-3,5'
        x, y    top-left corner in points (72 pt = 1 inch), origin top-left of the page as displayed
        w, h    box size in points

    text : text, size, color '#rrggbb', align 'auto|left|center|right', bold, shrink, font
    image: data  (data-URL or base64 of a PNG/JPEG; PNG transparency is kept - good for signatures and
           imported stamp pictures), angle (degrees clockwise, optional)
    stamp: text, color, border (bool), angle (degrees clockwise), date_text (optional 2nd line), font

    Returns (pdf_bytes, warnings).
    """
    doc = _open(pdf)
    warnings: list[str] = []
    for n, it in enumerate(items, 1):
        kind = it.get("kind", "text")
        if kind in ("text", "stamp") and not str(it.get("text", "")).strip():
            continue
        pages = _pages_for(it, len(doc))
        if not pages:
            warnings.append(f"Item {n}: no valid pages selected")
            continue
        if not all(0 <= p < len(doc) for p in pages):
            warnings.append(f"Item {n}: page {int(it.get('page', 0)) + 1} does not exist")
            continue
        rect = pymupdf.Rect(it["x"], it["y"], it["x"] + max(it.get("w", 200), 5), it["y"] + max(it.get("h", 30), 5))
        try:
            if kind == "image":
                data = _decode_data_url(it.get("data", ""))
                ang = float(it.get("angle", 0) or 0)
                for p in pages:
                    _draw_image(doc[p], rect, data, ang)
            elif kind == "stamp":
                for p in pages:
                    _draw_stamp(doc[p], rect, it)
            else:
                worst = 1.0
                for p in pages:
                    scale = _draw_text(
                        doc[p], rect, it["text"],
                        size=float(it.get("size", 12)), color=it.get("color", "#000000"),
                        align=it.get("align", "auto"), bold=bool(it.get("bold", False)),
                        shrink=bool(it.get("shrink", True)), font=it.get("font"),
                    )
                    worst = -1.0 if scale < 0 or worst < 0 else min(worst, scale)
                if worst < 0:
                    warnings.append(f"Item {n}: text does not fit in its box (make the box bigger or turn on shrink)")
                elif worst < 0.999:
                    warnings.append(f"Item {n}: text was shrunk to {round(worst * 100)}% to fit its box")
        except Exception as e:
            warnings.append(f"Item {n} ({kind}) could not be added: {e}")
    return _to_bytes(doc), warnings


overlay_text = apply_items          # old name, still works


# --------------------------------------------------------------------------
# Stamp presets (editable: put a stamps.json next to the app)
# --------------------------------------------------------------------------
def list_stamps() -> list[dict]:
    for base in (app_dir(), bundle_dir()):
        f = base / "stamps.json"
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                break
    return [{"name": "APPROVED", "text": "APPROVED", "color": "#15803d"}]


# --------------------------------------------------------------------------
# Compress
# --------------------------------------------------------------------------
COMPRESS_LEVELS = {
    #            images above this dpi | are resampled to | JPEG quality
    "light":    {"threshold": 250, "target": 200, "quality": 85},
    "balanced": {"threshold": 170, "target": 130, "quality": 65},
    "strong":   {"threshold": 120, "target": 96,  "quality": 45},
}

# A ladder from mildest to most aggressive, used when the person gives a target file size instead
# of picking Light/Balanced/Strong. Roughly: light, between light and balanced, balanced, between
# balanced and strong, strong, then three steps stronger still for a tight target.
TARGET_LADDER = [
    {"threshold": 250, "target": 200, "quality": 85},
    {"threshold": 200, "target": 160, "quality": 75},
    {"threshold": 170, "target": 130, "quality": 65},
    {"threshold": 140, "target": 110, "quality": 55},
    {"threshold": 120, "target": 96,  "quality": 45},
    {"threshold": 100, "target": 80,  "quality": 36},
    {"threshold": 90,  "target": 65,  "quality": 28},
    {"threshold": 80,  "target": 50,  "quality": 20},
]


def _try_compress(original: bytes, params: dict, grayscale: bool, strip_metadata: bool, subset_fonts: bool) -> tuple[bytes, list[str]]:
    """One compression attempt at a given aggressiveness. Always starts fresh from `original`."""
    doc = _open(original)
    notes: list[str] = []
    try:
        doc.rewrite_images(dpi_threshold=params["threshold"], dpi_target=params["target"], quality=params["quality"], set_to_gray=grayscale)
    except Exception as e:
        notes.append(f"Images could not be re-compressed ({e}); other savings were still applied.")
    if subset_fonts:
        try:
            doc.subset_fonts()
        except Exception:
            pass  # optional (needs fontTools); harmless to skip
    if strip_metadata:
        try:
            doc.scrub(attached_files=False, clean_pages=True, embedded_files=False, hidden_text=False, javascript=True,
                      metadata=True, redactions=False, redact_images=0, remove_links=False, reset_fields=False,
                      reset_responses=False, thumbnails=True, xml_metadata=True)
        except Exception:
            notes.append("Metadata could not be removed.")
    data = doc.tobytes(garbage=4, clean=True, deflate=True, deflate_images=True, deflate_fonts=True, use_objstms=True)
    return data, notes


def compress_pdf(
    pdf: bytes | str | Path,
    level: str = "balanced",
    grayscale: bool = False,
    strip_metadata: bool = False,
    target_bytes: int | None = None,
) -> tuple[bytes, dict]:
    """
    Shrink a PDF: downsample and re-encode large images, drop unused objects, compress streams.

    With `target_bytes` set, `level` is ignored: the file is compressed at increasing strength
    (a fixed ladder from light to very strong) until it fits the target size or the strongest
    setting has been tried, whichever comes first - each attempt starts over from the original,
    so quality is never lost twice. Returns (pdf_bytes, info) where info = {original, new,
    saved_pct, notes[], target_bytes, target_met}. If compression would make the file bigger,
    the original bytes are returned unchanged.
    """
    original = pdf if isinstance(pdf, (bytes, bytearray)) else Path(pdf).read_bytes()
    original = bytes(original)

    if target_bytes:
        if len(original) <= target_bytes:
            return original, {"original": len(original), "new": len(original), "saved_pct": 0.0,
                               "notes": ["This file is already at or under your target size."],
                               "target_bytes": target_bytes, "target_met": True}
        best_data, best_notes = original, []
        for params in TARGET_LADDER:
            data, notes = _try_compress(original, params, grayscale, strip_metadata, subset_fonts=True)
            if len(data) < len(best_data):
                best_data, best_notes = data, notes
            if len(data) <= target_bytes:
                saved = round((1 - len(data) / len(original)) * 100, 1)
                return data, {"original": len(original), "new": len(data), "saved_pct": saved, "notes": notes,
                               "target_bytes": target_bytes, "target_met": True}
        # Never got under target: hand back the smallest attempt reached, and say so plainly.
        saved = round((1 - len(best_data) / len(original)) * 100, 1) if len(best_data) < len(original) else 0.0
        notes = best_notes + ["Could not get under your target size without the images becoming unusably soft. "
                               "This is the smallest the tool could make it while keeping it readable."]
        return best_data, {"original": len(original), "new": len(best_data), "saved_pct": saved, "notes": notes,
                            "target_bytes": target_bytes, "target_met": False}

    p = COMPRESS_LEVELS.get(level, COMPRESS_LEVELS["balanced"])
    data, notes = _try_compress(original, p, grayscale, strip_metadata, subset_fonts=(level != "light"))
    if len(data) >= len(original):
        notes.append("This file is already well optimised - nothing more could be saved, so it was left unchanged.")
        data = original
    saved = round((1 - len(data) / len(original)) * 100, 1) if original else 0.0
    return data, {"original": len(original), "new": len(data), "saved_pct": saved, "notes": notes}


# --------------------------------------------------------------------------
# 2. Fill form fields
# --------------------------------------------------------------------------
_T = pymupdf
_TYPE_NAMES = {
    _T.PDF_WIDGET_TYPE_TEXT: "text",
    _T.PDF_WIDGET_TYPE_CHECKBOX: "checkbox",
    _T.PDF_WIDGET_TYPE_RADIOBUTTON: "radio",
    _T.PDF_WIDGET_TYPE_COMBOBOX: "choice",
    _T.PDF_WIDGET_TYPE_LISTBOX: "choice",
}
_MULTILINE_FLAG = 4096


def list_fields(pdf: bytes | str | Path | pymupdf.Document) -> list[dict]:
    """
    Describe every fillable field (radio buttons are grouped by name). Also reports every place
    (page + box) each field's widget actually sits, so a caller can show it where it really is on the
    page - some PDF forms give a field a misleading name, an odd tab order, a box that is too small to
    read, or reuse one name for several unrelated boxes, and "locations" is what makes those visible.
    """
    doc = pdf if isinstance(pdf, pymupdf.Document) else _open(pdf)
    fields: dict[str, dict] = {}
    for pno, page in enumerate(doc):
        for w in page.widgets() or []:
            kind = _TYPE_NAMES.get(w.field_type)
            if not kind:
                continue  # buttons / signatures
            name = w.field_name
            rect = [round(v, 1) for v in w.rect]
            f = fields.get(name)
            if f is None:
                f = fields[name] = {
                    "name": name,
                    "type": kind,
                    "page": pno,
                    "rect": rect,
                    "value": w.field_value if kind in ("text", "choice") else None,
                    "multiline": bool(w.field_flags & _MULTILINE_FLAG) if kind == "text" else False,
                    "options": [],
                    "locations": [],  # every widget for this field name: {page, rect}
                }
                if kind == "choice":
                    f["options"] = [
                        (c[0] if isinstance(c, (list, tuple)) else c) for c in (w.choice_values or [])
                    ]
            if kind == "radio":
                f["options"].append(w.on_state())
            f["locations"].append({"page": pno, "rect": rect})
    for f in fields.values():
        # Radios legitimately have one widget per option; for everything else, more than one widget
        # sharing a name means typing a value fills every one of those boxes at once.
        f["shared"] = f["type"] != "radio" and len(f["locations"]) > 1
    return list(fields.values())


def fill_form(
    pdf: bytes | str | Path,
    values: dict[str, Any],
    flatten: bool = False,
    font_size: float | None = None,
    font: str | None = None,
) -> tuple[bytes, list[str]]:
    """
    values: {field_name: value}
        text / choice   string
        checkbox        True/False
        radio           one of the field's options (see list_fields)

    Fields whose value contains Thaana are drawn as real shaped text over the field
    and the widget is removed (PDF form widgets cannot shape Thaana themselves).
    Everything else is filled normally and stays editable, unless flatten=True.
    """
    doc = _open(pdf)
    warnings: list[str] = []
    seen: set[str] = set()

    for page in doc:
        for w in list(page.widgets() or []):
            name = w.field_name
            if name not in values:
                continue
            seen.add(name)
            val = values[name]
            kind = _TYPE_NAMES.get(w.field_type)

            if kind in ("text", "choice"):
                val = "" if val is None else str(val)
                if has_thaana(val):
                    r = pymupdf.Rect(w.rect)
                    multiline = bool(w.field_flags & _MULTILINE_FLAG)
                    size = font_size or (w.text_fontsize if w.text_fontsize > 0 else (11 if multiline else min(12.0, r.height * 0.7)))
                    inner = pymupdf.Rect(r.x0 + 2, r.y0 + 1, r.x1 - 2, r.y1 - 1)
                    if not multiline:
                        inner.y0 += max(0.0, (inner.height - size * 1.4) / 2)
                    scale = _draw_text(page, inner, val, size=size, font=font)
                    if scale < 0:
                        warnings.append(f"Field '{name}': text does not fit")
                    elif scale < 0.999:
                        warnings.append(f"Field '{name}': text shrunk to {round(scale * 100)}%")
                    page.delete_widget(w)
                else:
                    w.field_value = val
                    w.update()
            elif kind == "checkbox":
                w.field_value = bool(val) if not isinstance(val, str) else val.lower() in ("1", "true", "yes", "on")
                w.update()
            elif kind == "radio":
                w.field_value = (w.on_state() == val)
                w.update()

    for name in values:
        if name not in seen:
            warnings.append(f"Field '{name}' was not found in this PDF")

    if flatten:
        doc.bake(annots=True, widgets=True)
    return _to_bytes(doc), warnings


# --------------------------------------------------------------------------
# 3. Generate a new PDF from a template
# --------------------------------------------------------------------------
def _paragraphs(text: Any) -> Markup:
    """Jinja filter: each non-empty line becomes a <p> with its own text direction."""
    parts = [p.strip() for p in str(text or "").splitlines() if p.strip()]
    return Markup("".join(f"<p{_attrs(p)}>{escape(fix_numbers(p))}</p>" for p in parts))


def _attrs(text: Any) -> Markup:
    """Jinja filter: ' dir="rtl" class="dv"' chosen from the text, for use inside a tag."""
    cls = "dv" if has_thaana(text) else "en"
    return Markup(f' dir="{direction(text)}" class="{cls}"')


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["dir"] = direction
    env.filters["attrs"] = _attrs
    env.filters["paragraphs"] = _paragraphs
    return env


def list_templates() -> list[dict]:
    """
    Every pdf_templates/*.html file. An optional <name>.json next to it describes the form:
        {"title": "...", "fields": [{"name": "subject", "label": "Subject", "type": "text|textarea", "default": ""}]}
    Without a .json file, every {{ variable }} in the template becomes a text box.
    """
    env = _env()
    out = []
    for f in sorted(TEMPLATE_DIR.glob("*.html")):
        info: dict = {"id": f.stem, "title": f.stem.replace("_", " ").title(), "fields": []}
        side = f.with_suffix(".json")
        if side.exists():
            info.update(json.loads(side.read_text(encoding="utf-8")))
        else:
            ast = env.parse(f.read_text(encoding="utf-8"))
            info["fields"] = [
                {"name": v, "label": v, "type": "text"} for v in sorted(meta.find_undeclared_variables(ast))
            ]
        out.append(info)
    return out


def html_to_pdf(
    html: str,
    page_size: str = "a4",
    margins: tuple[float, float, float, float] = (56, 56, 56, 56),  # left, top, right, bottom
    page_numbers: bool = False,
    font: str | None = None,
) -> bytes:
    """Flow HTML (+ our Thaana CSS) onto as many pages as needed."""
    font_css, archive = _font_setup(font)
    story = pymupdf.Story(html=wrap_thaana(html), user_css=font_css + STORY_CSS, archive=archive)
    media = pymupdf.paper_rect(page_size)
    l, t, r, b = margins
    where = media + (l, t, -r, -b)

    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    more = True
    while more:
        dev = writer.begin_page(media)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()

    doc = pymupdf.open(stream=buf.getvalue(), filetype="pdf")
    if page_numbers:
        n = len(doc)
        for i, page in enumerate(doc, 1):
            pr = page.rect
            page.insert_textbox(
                pymupdf.Rect(0, pr.height - 40, pr.width, pr.height - 22),
                f"{i} / {n}",
                fontsize=9,
                fontname="helv",
                align=1,
                color=(0.4, 0.4, 0.4),
            )
    return _to_bytes(doc)


def generate_pdf(template_id: str, values: dict[str, Any], page_numbers: bool = False, font: str | None = None) -> bytes:
    """Render pdf_templates/<template_id>.html with `values` and return the PDF."""
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", template_id):
        raise ValueError("bad template id")
    tpl = _env().get_template(f"{template_id}.html")
    info = next((t for t in list_templates() if t["id"] == template_id), {})
    opts = info.get("page", {})
    values = {k: (fix_numbers(v) if isinstance(v, str) else v) for k, v in values.items()}
    return html_to_pdf(
        tpl.render(**values),
        page_size=opts.get("size", "a4"),
        margins=tuple(opts.get("margins", (56, 56, 56, 56))),
        page_numbers=page_numbers,
        font=font,
    )
