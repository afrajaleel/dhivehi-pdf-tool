# Dhivehi PDF Tool

A small local web app that writes Dhivehi (Thaana) onto PDFs correctly: right-to-left, fili in the right place,
mixed Dhivehi + English + numbers in the right order. Everything runs on your computer; nothing is uploaded anywhere.

| Tab | What it does |
|---|---|
| Edit PDF | Add text (Dhivehi / English), signatures and stamps to any PDF, including scans |
| Fill a form | Fill the fillable fields of a PDF form, with every field shown right on the page |
| New from template | Make a new PDF from an HTML template (an official letter is included) |
| Compress | Make a PDF smaller (Light / Balanced / Strong) and see the before/after size |
| Help & About | Full instructions for every tool, plus the version number and contact details |

## Run it

Needs Python 3.9+.

* Windows: double-click `run.bat`
* Mac / Linux: `./run.sh`
* Or by hand: `pip install -r requirements.txt`, then `python app.py`, then open http://127.0.0.1:5000

## Continuing to edit a result

Every result (a filled form, an edited PDF, a generated letter, a compressed file) has a
**Continue editing this PDF** button next to Download. It re-opens that exact result as the
working PDF, so you can fill a form and then add a signature or stamp, or compress and then edit,
all without saving and re-uploading a file in between.

## Fill a form

The page is shown with every field outlined on it, so you can click and type where the field actually is,
not just in a plain list. This also surfaces problems some PDF forms have:

* A field too small or badly placed to use is outlined in red with a **Type here instead** button, which
  switches to *Edit PDF* and drops a normal, resizable text box in the same spot.
* A field name reused in more than one place is marked **SAME EVERYWHERE** — typing a value fills every
  one of those spots, since that is how the PDF itself was built.

## Signatures and stamps

* **Signature:** click *Signature*, then draw with a mouse/finger/pen, or upload a photo or scan of your signature
  (the white background is made transparent). It is placed on the page; drag and resize it. Signatures you keep are saved
  on this computer for next time. This puts a *picture* of your signature on the PDF. It is not a certificate-based digital signature.
* **Stamp:** click *Stamp* and pick a preset (APPROVED, RECEIVED, PAID ...) or *Custom*. You can change the text
  (Dhivehi works), colour, tilt, border, and add a date line.
* **Your own picture as a stamp:** in the *Stamp* menu choose *Import a picture* (a seal, logo or scan of a physical stamp;
  PNG or JPG). Tick "Make the white background transparent" so only the ink shows. It is placed on the page, and you can
  move, resize and tilt it. Imported pictures are kept in the Stamp menu for next time.
* **Which pages:** every item has *Put it on*: this page, all pages, first, last, or a list such as `1-3, 5`.
* **Your own stamp presets:** edit `stamps.json` (next to the app) and add lines like
  `{"name": "Label", "text": "Text on the stamp", "color": "#15803d"}`. Dhivehi text is fine there.

## Compress

Downsamples and re-encodes large images, removes unused data and compresses the rest. Scans and photo-heavy PDFs
shrink a lot; text-only PDFs are already small. If compressing would not make the file smaller you get the original back.
Options: convert images to greyscale, and remove metadata. Instead of Light/Balanced/Strong you can
choose **Target a file size** and give a size (e.g. "under 2 MB"); the tool tries progressively
stronger settings until the result fits, or reports the smallest it could reach if your target isn't
achievable without the images becoming unusably soft.

## Notes

* **Fonts.** Every tab has a Font menu with a live sample. It lists the bundled Noto Sans Thaana, any font you add
  with **Add font...** (a .ttf/.otf that contains Thaana), and Thaana fonts already installed on your computer
  (on Windows, for example, Faruma or MV Boli). In Overlay each text box can have its own font. Added fonts are kept in
  the `fonts` folder next to the app. A bold version is used automatically when a matching file is present
  (e.g. `Foo-Regular.ttf` + `Foo-Bold.ttf`); otherwise Bold has no effect for that font.
* **Size.** Thaana looks smaller than Latin at the same point size. In Overlay use about 16-18 pt to match 12 pt English.
  Templates handle this automatically for the bundled font; other fonts may need a slightly different size.
* **Forms.** PDF form fields cannot display Thaana on their own. A field that gets Dhivehi text is drawn as real text
  over the field and the field itself is removed (so that one can no longer be edited). Fields with English, numbers or
  ticks stay editable unless you tick "Flatten".
* **Numbers after Dhivehi.** A date such as `ތާރީޚް: 19 September 2026` normally comes out scrambled
  (`September 2026 19`) because of how right-to-left rules treat digits. The tool inserts an invisible left-to-right
  mark before numbers to prevent that.
* **Not supported:** password-protected PDFs, signing, editing existing text in a PDF (it only adds).

## Adding your own templates

Put `name.html` in `pdf_templates/` and use `{{ variable }}` for the parts that change. The form is built automatically.

* `<p{{ x|attrs }}>` adds the correct text direction and Dhivehi sizing to a tag, based on what `x` contains
* `{{ body|paragraphs }}` turns a multi-line value into one paragraph per line

For nicer labels, textareas, defaults and margins, add `name.json` next to it (see `letter.json`).
Please have a Dhivehi speaker check the default labels in `letter.json`.

## Use as a library

See `example_script.py`.

## Windows desktop app

`launcher.py` runs the tool in its own window (Edge WebView2, already part of Windows 10/11) instead of a browser tab.
To build a standalone folder that runs without Python installed:

1. On a Windows PC with Python 3.9+, double-click `build.bat`.
2. Share the whole `dist\DhivehiPDF` folder (zip it). Users run `DhivehiPDF.exe`.

Templates in `dist\DhivehiPDF\pdf_templates` and stamp presets in `dist\DhivehiPDF\stamps.json` can be edited without rebuilding.

If the native window cannot start, the app opens in the default browser instead, and `launcher.py` now says *why*:
on Windows it asks pywebview for the Edge WebView2 backend explicitly (instead of letting it silently fall back
to something else), so a missing **Microsoft Edge WebView2 Runtime** - the most common cause, on older or
locked-down Windows images - is detected and reported in the message box with a direct download link
(https://go.microsoft.com/fwlink/p/?LinkId=2124703), rather than just opening a browser tab with no explanation.
For any other cause, the full error is written to `window_error.log` next to `DhivehiPDF.exe` for troubleshooting.

## Version number

The version shown in *Help & About* comes from `version.py`. Change `APP_VERSION` there before building a new release.

