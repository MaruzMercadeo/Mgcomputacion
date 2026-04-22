@echo off
REM Arranca la app Flask. Lo invoca Windows al iniciar sesion.
REM Usa start_server.vbs como wrapper si quieres que no se vea la consola.

setlocal

REM Ir a la raiz del proyecto (un nivel arriba de /scripts)
cd /d "%~dp0\.."

REM Crear carpeta de logs si no existe
if not exist "logs" mkdir "logs"

REM Activar venv
if not exist "venv\Scripts\activate.bat" (
  echo [%date% %time%] venv no encontrado. Ejecuta primero: python -m venv venv ^&^& pip install -r requirements.txt >> logs\flask.log
  exit /b 1
)
call venv\Scripts\activate.bat

REM Asegurar que .env existe (sino copiar el example)
if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo [%date% %time%] .env creado desde .env.example. Edita SECRET_KEY antes de exponer a internet. >> logs\flask.log
)

REM Log de arranque
echo. >> logs\flask.log
echo ================================================================ >> logs\flask.log
echo [%date% %time%] Arrancando flask en puerto 5555 >> logs\flask.log
echo ================================================================ >> logs\flask.log

REM Arrancar Flask (bloqueante, los logs van al archivo)
flask run >> logs\flask.log 2>&1
