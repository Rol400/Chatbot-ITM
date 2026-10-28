@echo off
setlocal
cd /d "%~dp0"
title Practica de entrevistas - servidor

if not exist ".venv\Scripts\python.exe" goto :not_installed
if not exist ".env" goto :not_installed

echo.
echo  Iniciando la pagina... se abrira sola en tu navegador.
echo  Usa Chrome o Edge para que funcione el microfono.
echo  Para apagarla, cierra esta ventana.
echo.
".venv\Scripts\python.exe" manage.py migrate --noinput >nul
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 4; Start-Process 'http://127.0.0.1:8000'"
".venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000
pause
exit /b 0

:not_installed
echo.
echo  Todavia no esta instalado. Primero haz doble clic en instalar.bat
echo.
pause
exit /b 1
