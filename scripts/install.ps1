# FRIDAY — installation locale (gratuite, sans clé API).
# Usage : powershell -ExecutionPolicy Bypass -File scripts\install.ps1
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

Step 'Vérification de uv'
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host 'uv est introuvable. Installe-le (gratuit) : winget install --id=astral-sh.uv -e' -ForegroundColor Yellow
    exit 1
}

Step 'Vérification de Claude Code'
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Host 'Le binaire claude est introuvable. Installe Claude Code puis connecte-toi avec `claude`.' -ForegroundColor Yellow
    exit 1
}
foreach ($var in 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN') {
    if (Test-Path "env:$var") {
        Write-Host "Attention : $var est définie. FRIDAY la retirera de l'environnement de claude." -ForegroundColor Yellow
    }
}

Step 'Python 3.12 et dépendances'
uv python find 3.12 *> $null
if ($LASTEXITCODE -ne 0) { uv python install 3.12 }
uv sync

Step 'Dossiers locaux'
foreach ($dir in 'data', 'logs', 'models', 'workspace') {
    New-Item -ItemType Directory -Force (Join-Path $root $dir) | Out-Null
}

Step 'Configuration'
$config = Join-Path $root 'config\friday.yaml'
if (Test-Path $config) {
    Write-Host 'config\friday.yaml existe déjà, conservé.'
} else {
    Copy-Item (Join-Path $root 'config\friday.example.yaml') $config
    Write-Host 'config\friday.yaml créé à partir de l''exemple.'
}

# Modèles audio : téléchargés une seule fois dans models\ (gratuits, utilisés hors ligne).
Step 'Voix de FRIDAY (Piper, voix française)'
$voice = 'fr_FR-siwis-medium'   # doit correspondre à tts.voice dans config\friday.yaml
if (Test-Path (Join-Path $root "models\piper\$voice.onnx")) {
    Write-Host "Voix $voice déjà présente."
} else {
    & (Join-Path $root '.venv\Scripts\python.exe') -m piper.download_voices $voice --download-dir (Join-Path $root 'models\piper')
}
# À venir : phase 4 (faster-whisper, Silero VAD) et phase 5 (openWakeWord).

Step 'Périphériques audio disponibles'
& (Join-Path $root '.venv\Scripts\friday.exe') devices

Write-Host ''
Write-Host 'Installation terminée. Choisis ton micro dans config\friday.yaml (audio.input_device).' -ForegroundColor Green
