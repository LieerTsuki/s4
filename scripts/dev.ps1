param(
    [ValidateSet('setup', 'migrate', 'api', 'worker', 'web', 'test', 'bootstrap', 'status')]
    [string]$Action = 'status',
    [string]$Username = '',
    [string]$DisplayName = '',
    [string]$PersonId = ''
)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskUv = Join-Path $taskRoot '.tools\uv-runtime\bin\uv.exe'
if (-not (Test-Path -LiteralPath $taskUv)) {
    $taskUvCommand = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $taskUvCommand) { throw 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/' }
    $taskUv = $taskUvCommand.Source
}
$env:UV_PROJECT_ENVIRONMENT = Join-Path $taskRoot '.venv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $taskRoot '.tools\python'
$env:UV_LINK_MODE = 'copy'
$taskEnvPath = Join-Path $taskRoot '.env'
if ($Action -eq 'setup' -and -not (Test-Path -LiteralPath $taskEnvPath)) {
    $taskOwnerSecret = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
    $taskAppSecret = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
    $taskLines = @(
        "S4_DB_OWNER_PASSWORD=$taskOwnerSecret", "S4_DB_APP_PASSWORD=$taskAppSecret",
        "S4_DATABASE_URL=postgresql+asyncpg://s4_app:${taskAppSecret}@127.0.0.1:55434/s4_dev",
        "S4_MIGRATION_DATABASE_URL=postgresql+asyncpg://s4_owner:${taskOwnerSecret}@127.0.0.1:55434/s4_dev",
        "S4_TEST_DATABASE_URL=postgresql+asyncpg://s4_owner:${taskOwnerSecret}@127.0.0.1:55434/s4_test",
        "S4_DATA_DIR=$($taskRoot.Replace('\','/'))/var", 'S4_COOKIE_SECURE=false',
        'S4_ALLOWED_ORIGIN=http://localhost:5174', 'S4_EXTERNAL_ALIGNMENT_CONFIRMED=false'
    )
    [IO.File]::WriteAllLines($taskEnvPath, $taskLines, [Text.UTF8Encoding]::new($false))
    Write-Output 'Created local .env with random database secrets (values hidden).'
}
if (Test-Path -LiteralPath $taskEnvPath) {
    foreach ($taskLine in [IO.File]::ReadAllLines($taskEnvPath)) {
        if ($taskLine -match '^([A-Z][A-Z0-9_]*)=(.*)$') {
            [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process')
        }
    }
}
Push-Location $taskRoot
try {
    switch ($Action) {
        setup {
            & $taskUv python install 3.11
            if ($LASTEXITCODE -ne 0) { throw 'Python setup failed.' }
            & $taskUv sync --project backend --extra dev --locked
            if ($LASTEXITCODE -ne 0) { throw 'Python dependency setup failed.' }
            & docker compose --env-file .env -f deploy/compose.yml -f deploy/compose.dev.yml up -d --wait db
            if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL startup failed. Check Docker Desktop.' }
            Push-Location frontend
            try { & npm.cmd ci; if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency setup failed.' } }
            finally { Pop-Location }
        }
        migrate {
            Push-Location backend
            try { & '..\.venv\Scripts\python.exe' -m alembic upgrade head; if ($LASTEXITCODE -ne 0) { throw 'Migration failed.' } }
            finally { Pop-Location }
        }
        api { & '.\.venv\Scripts\python.exe' -m uvicorn openkb_s4.main:app --host 127.0.0.1 --port 8004 }
        worker { & '.\.venv\Scripts\python.exe' -m openkb_s4.worker }
        web {
            Push-Location frontend
            try { & npm.cmd run dev -- --host 127.0.0.1 --port 5174 }
            finally { Pop-Location }
        }
        test {
            if (-not $env:S4_TEST_DATABASE_URL -or ($env:S4_TEST_DATABASE_URL -notmatch '/s4_test(?:\?.*)?$')) {
                throw 'Tests require the isolated s4_test database in S4_TEST_DATABASE_URL.'
            }
            Push-Location backend
            try {
                $taskOriginalMigrationUrl = $env:S4_MIGRATION_DATABASE_URL
                try {
                    $env:S4_MIGRATION_DATABASE_URL = $env:S4_TEST_DATABASE_URL
                    & '..\.venv\Scripts\python.exe' -m alembic upgrade head
                    if ($LASTEXITCODE -ne 0) { throw 'Test database migration failed.' }
                }
                finally { $env:S4_MIGRATION_DATABASE_URL = $taskOriginalMigrationUrl }
                & '..\.venv\Scripts\python.exe' -m pytest --cov=openkb_s4 --cov-report=term-missing --cov-fail-under=80; if ($LASTEXITCODE -ne 0) { throw 'Backend verification failed.' }
                & '..\.venv\Scripts\python.exe' -m ruff check src tests; if ($LASTEXITCODE -ne 0) { throw 'Backend lint failed.' }
                & '..\.venv\Scripts\python.exe' -m mypy; if ($LASTEXITCODE -ne 0) { throw 'Backend type check failed.' }
            }
            finally { Pop-Location }
            Push-Location frontend
            try {
                & npm.cmd test -- --run; if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed.' }
                & npm.cmd run build; if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
                & npm.cmd run lint; if ($LASTEXITCODE -ne 0) { throw 'Frontend lint failed.' }
            }
            finally { Pop-Location }
        }
        bootstrap {
            if (-not $Username -or -not $DisplayName -or -not $PersonId) { throw 'Supply -Username, -DisplayName and -PersonId; password is prompted securely.' }
            & '.\.venv\Scripts\python.exe' -m openkb_s4.cli bootstrap --username $Username --display-name $DisplayName --person-id $PersonId
        }
        status { & docker compose --env-file .env -f deploy/compose.yml -f deploy/compose.dev.yml ps }
    }
    if ($LASTEXITCODE -ne 0) { throw "Action $Action failed (exit $LASTEXITCODE)." }
}
finally { Pop-Location }
