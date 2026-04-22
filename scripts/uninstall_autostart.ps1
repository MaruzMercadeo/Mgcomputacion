# Quita el autoarranque de la app.

$startupDir = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupDir 'MGComputacion.lnk'

if (Test-Path $shortcutPath) {
    Remove-Item $shortcutPath
    Write-Host "Shortcut quitado: $shortcutPath"
} else {
    Write-Host "No hay shortcut en: $shortcutPath (nada que hacer)"
}
