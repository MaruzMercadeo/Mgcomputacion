# Registra la app para arrancar automaticamente al iniciar sesion en Windows.
# Uso: click derecho > Ejecutar con PowerShell
# O desde una terminal PowerShell: powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$vbsPath = Join-Path $projectRoot 'scripts\start_server.vbs'

if (-not (Test-Path $vbsPath)) {
    Write-Error "No se encontro $vbsPath"
    exit 1
}

$startupDir = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupDir 'MGComputacion.lnk'

$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = 'wscript.exe'
$shortcut.Arguments = '"' + $vbsPath + '"'
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = 'MGComputacion Flask app autostart'
$shortcut.Save()

Write-Host "OK. Shortcut creado en:"
Write-Host "  $shortcutPath"
Write-Host ""
Write-Host "La proxima vez que inicies sesion en Windows, la app levantara sola en http://127.0.0.1:5555"
Write-Host "Logs: $projectRoot\logs\flask.log"
Write-Host ""
Write-Host "Para desinstalar ejecuta: scripts\uninstall_autostart.ps1"
