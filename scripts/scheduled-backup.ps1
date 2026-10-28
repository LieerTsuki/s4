param([string]$ApiContainer = 'openkb-s4-api-1')
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskPython = Join-Path $taskRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'The controlled local Python environment is missing.' }
Push-Location $taskRoot
try {
    & $taskPython scripts/backup_restore.py backup --api-container $ApiContainer
    if ($LASTEXITCODE -ne 0) { throw 'Scheduled S4 backup failed; inspect the safe operation audit.' }
}
finally { Pop-Location }
