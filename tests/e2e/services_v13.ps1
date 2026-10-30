param([ValidateSet('api','worker','web')][string]$Service)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
foreach ($taskLine in [IO.File]::ReadAllLines((Join-Path $taskRoot '.env.v13-e2e'))) {
    if ($taskLine -match '^([A-Z][A-Z0-9_]*)=(.*)$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process')
    }
}
Set-Location $taskRoot
switch ($Service) {
    api { & '.\.venv\Scripts\python.exe' -m uvicorn openkb_s4.main:app --host 127.0.0.1 --port 8004 }
    worker { & '.\.venv\Scripts\python.exe' -m openkb_s4.worker }
    web { Set-Location frontend; & npm.cmd run dev -- --host 127.0.0.1 --port 5176 }
}
exit $LASTEXITCODE
