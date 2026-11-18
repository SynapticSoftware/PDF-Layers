@echo off
setlocal
cd /d "%~dp0"
if not defined PDF_LAYERS_PYTHON set "PDF_LAYERS_PYTHON=py -3.12"
%PDF_LAYERS_PYTHON% -m venv .venv || exit /b 1
.venv\Scripts\python.exe -m pip install -r requirements-build.txt || exit /b 1
.venv\Scripts\python.exe -m unittest -v || exit /b 1
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name PDFLayers --icon icon.png --add-data "icon.png:." --collect-all pymupdf pdf_layers.py || exit /b 1
