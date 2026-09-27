# FRIDAY — démarrage automatique à l'ouverture de session Windows (tâche planifiée « FRIDAY »).
# Installer    : powershell -ExecutionPolicy Bypass -File scripts\autostart.ps1
# Désinstaller : powershell -ExecutionPolicy Bypass -File scripts\autostart.ps1 -Desinstaller
# État         : powershell -ExecutionPolicy Bypass -File scripts\autostart.ps1 -Etat
param(
    [switch]$Desinstaller,
    [switch]$Etat
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$root = Split-Path -Parent $PSScriptRoot
$taskName = 'FRIDAY'
$user = "$env:USERDOMAIN\$env:USERNAME"

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if ($Etat) {
    if ($existing) {
        $info = $existing | Get-ScheduledTaskInfo
        Write-Host "Démarrage automatique : activé ($($existing.State))."
        Write-Host "Programme : $($existing.Actions[0].Execute) $($existing.Actions[0].Arguments)"
        Write-Host "Dernier lancement : $($info.LastRunTime) (code $($info.LastTaskResult))"
    } else {
        Write-Host 'Démarrage automatique : désactivé.'
    }
    exit 0
}

if ($Desinstaller) {
    if ($existing) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host 'Démarrage automatique désactivé : la tâche « FRIDAY » est supprimée.' -ForegroundColor Green
    } else {
        Write-Host 'Aucune tâche « FRIDAY » : rien à faire.'
    }
    exit 0
}

$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) {
    Write-Host "Introuvable : $pythonw. Lancez d'abord scripts\install.ps1." -ForegroundColor Yellow
    exit 1
}

# pythonw : aucune console. FRIDAY s'ouvre sur « Chargement… » puis annonce sa session.
$action = New-ScheduledTaskAction -Execute $pythonw -Argument '-m friday' -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$trigger.Delay = 'PT30S'   # laisse Windows, le son et le réseau démarrer
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings `
    -Description "FRIDAY, assistant vocal local ($root)" -Force | Out-Null

Write-Host "Démarrage automatique activé : FRIDAY se lancera 30 s après l'ouverture de session." -ForegroundColor Green
Write-Host 'Pour le désactiver : powershell -ExecutionPolicy Bypass -File scripts\autostart.ps1 -Desinstaller'
