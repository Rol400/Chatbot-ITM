@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Instalador - Practica de entrevistas

echo.
echo  ==========================================================
echo    Instalador - solo se usa la primera vez
echo  ==========================================================
echo.

if not exist "manage.py" goto :no_project

rem ---------- 1. Python ----------
call :find_python
if defined PY goto :have_python

echo  [1/5] No encontre Python. Instalandolo, puede tardar unos minutos...
where winget >nul 2>nul
if errorlevel 1 goto :python_download
winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
call :find_python
if defined PY goto :have_python

:python_download
echo        Descargando Python desde python.org...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = 'Tls12'; Invoke-WebRequest -UseBasicParsing 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile (Join-Path $env:TEMP 'python-3.12.10-amd64.exe')"
if not exist "%TEMP%\python-3.12.10-amd64.exe" goto :python_failed
"%TEMP%\python-3.12.10-amd64.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0
call :find_python
if not defined PY goto :python_failed

:have_python
echo  [1/5] Python listo: %PY%

rem ---------- 2. Entorno virtual ----------
if exist ".venv\Scripts\python.exe" goto :have_venv
echo  [2/5] Creando el entorno del proyecto...
"%PY%" -m venv .venv
if errorlevel 1 goto :failed
:have_venv
set "VPY=%CD%\.venv\Scripts\python.exe"
echo  [2/5] Entorno listo.

rem ---------- 3. Paquetes ----------
echo  [3/5] Instalando Django y demas paquetes...
"%VPY%" -m pip install --upgrade pip --disable-pip-version-check -q
"%VPY%" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 goto :failed
echo  [3/5] Paquetes instalados.

rem ---------- 4. Llaves ----------
echo  [4/5] Configurando tus llaves...
"%VPY%" configurar_env.py
if errorlevel 1 goto :failed

rem ---------- 5. Base de datos ----------
echo.
echo  [5/5] Preparando la base de datos...
"%VPY%" manage.py migrate --noinput
if errorlevel 1 goto :failed

echo.
echo  ==========================================================
echo    Instalacion terminada.
echo    De ahora en adelante abre la pagina con iniciar.bat
echo  ==========================================================
echo.
choice /c SN /m "  Abrir la pagina ahora"
if errorlevel 2 exit /b 0
call "%~dp0iniciar.bat"
exit /b 0

rem ---------- Funciones y errores ----------
:find_python
set "PY="
for %%V in (313 312) do if not defined PY if exist "%LocalAppData%\Programs\Python\Python%%V\python.exe" set "PY=%LocalAppData%\Programs\Python\Python%%V\python.exe"
if defined PY exit /b 0
for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable if sys.version_info >= (3, 12) else '')" 2^>nul') do set "PY=%%P"
if defined PY exit /b 0
for /f "delims=" %%P in ('python -c "import sys; print(sys.executable if sys.version_info >= (3, 10) else '')" 2^>nul') do set "PY=%%P"
exit /b 0

:no_project
echo  No encuentro manage.py.
echo  Este archivo debe estar dentro de la carpeta del proyecto, junto a manage.py.
pause
exit /b 1

:python_failed
echo.
echo  No se pudo instalar Python automaticamente.
echo  Instalalo a mano desde https://www.python.org/downloads/
echo  y marca la casilla "Add python.exe to PATH". Despues vuelve a abrir instalar.bat
pause
exit /b 1

:failed
echo.
echo  Algo fallo en el paso anterior. Revisa el mensaje de arriba,
echo  verifica tu conexion a internet y vuelve a abrir instalar.bat
pause
exit /b 1
