@echo off
cd /d "%~dp0"
echo.
echo  Instalando dependencias...
pip install -q flask fpdf2
echo.
echo  Limpiando cache de Python...
if exist __pycache__ rmdir /s /q __pycache__
echo.
echo  Iniciando Heladeria App...
python app.py
pause
