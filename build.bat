@echo off
rem Builds dist\DhivehiPDF\DhivehiPDF.exe (run on Windows, needs Python 3.9+ from python.org)
cd /d "%~dp0"
if not exist .venv-build ( python -m venv .venv-build )
call .venv-build\Scripts\activate
pip install -r requirements-desktop.txt || goto :fail
pyinstaller --noconfirm --clean --windowed --name DhivehiPDF --icon icon.ico ^
  --collect-all webview --collect-submodules fontTools ^
  --add-data "fonts;fonts" --add-data "static;static" --add-data "pdf_templates;pdf_templates" --add-data "stamps.json;." --add-data "icon.ico;." ^
  launcher.py || goto :fail
rem Editable templates and stamp presets sit next to the exe
xcopy /E /I /Y pdf_templates dist\DhivehiPDF\pdf_templates >nul
copy /Y stamps.json dist\DhivehiPDF\stamps.json >nul
copy /Y "READ ME FIRST.txt" "dist\DhivehiPDF\READ ME FIRST.txt" >nul
echo.
echo Done. Share the whole folder: dist\DhivehiPDF  (run DhivehiPDF.exe)
pause
exit /b 0
:fail
echo Build failed - see messages above.
pause
exit /b 1
