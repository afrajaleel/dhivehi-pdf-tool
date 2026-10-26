"""Using the library directly, no web page needed (handy for batch jobs)."""
import pdf_core as core

# 1. Overlay text on an existing PDF
pdf = open("input.pdf", "rb").read()
out, warnings = core.overlay_text(pdf, [
    {"page": 0, "x": 350, "y": 120, "w": 200, "h": 30, "text": "ދިވެހިރާއްޖެ", "size": 18},
    {"page": 0, "x": 72,  "y": 120, "w": 200, "h": 30, "text": "Ahmed Ali",     "size": 12},
])
open("overlay.pdf", "wb").write(out)
print(warnings)

# 2. Fill a form (see field names with list_fields)
print(core.list_fields(pdf))
out, warnings = core.fill_form(pdf, {"full_name": "އަޙްމަދު", "agree": True})
open("filled.pdf", "wb").write(out)

# 3. Generate from a template in pdf_templates/
out = core.generate_pdf("letter", {"org": "...", "subject": "...", "body": "line 1\nline 2"}, page_numbers=True)
open("letter.pdf", "wb").write(out)

# 4. Stamp + signature image + compress
import base64
sig = "data:image/png;base64," + base64.b64encode(open("signature.png", "rb").read()).decode()
out, warnings = core.apply_items(pdf, [
    {"kind": "stamp", "page": 0, "pages": "all", "x": 380, "y": 40, "w": 180, "h": 56, "text": "APPROVED", "color": "#15803d", "angle": -8},
    {"kind": "image", "page": 0, "pages": "last", "x": 72, "y": 700, "w": 140, "h": 46, "data": sig},
])
small, info = core.compress_pdf(out, level="balanced")
print(info)          # {'original': ..., 'new': ..., 'saved_pct': ..., 'notes': []}
open("final.pdf", "wb").write(small)
