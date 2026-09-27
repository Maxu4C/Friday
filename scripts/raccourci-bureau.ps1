# Crée (ou recrée) le raccourci « FRIDAY » sur le Bureau : lance FRIDAY avec son interface,
# sans fenêtre de console.
# Usage : powershell -ExecutionPolicy Bypass -File scripts\raccourci-bureau.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) {
    Write-Host "Environnement Python introuvable : lancez d'abord scripts\install.ps1" -ForegroundColor Yellow
    exit 1
}

# Icône (anneau lumineux) générée localement, aucun visuel protégé.
$icon = Join-Path $root 'friday\ui\friday.ico'
if (-not (Test-Path $icon)) {
    & (Join-Path $root '.venv\Scripts\python.exe') -c "from friday.ui.tray import save_icon; from pathlib import Path; save_icon(Path(r'$icon'))"
}

$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'FRIDAY.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '-m friday'
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = "$icon,0"
$shortcut.Description = 'FRIDAY, assistante vocale locale'
$shortcut.Save()
Write-Host "Raccourci créé : $shortcutPath" -ForegroundColor Green
