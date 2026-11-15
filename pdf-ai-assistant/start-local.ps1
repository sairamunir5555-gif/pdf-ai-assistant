# Set-Location "C:\Users\saira\Downloads\pdf-ai-assistant\pdf-ai-assistant"; powershell -NoProfile -ExecutionPolicy Bypass -File .\start-local.ps1
$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$url = "http://localhost:8000"
$healthUrl = "http://127.0.0.1:8000/api/health"

Set-Location $projectRoot

$listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($listener) {
    try {
        $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3
    } catch {
        $health = $null
    }

    if ($health -and $health.status -eq "ok" -and
        $health.PSObject.Properties.Name -contains "llm_configured") {
        if (-not $health.llm_configured) {
            Write-Warning "OPENROUTER_API_KEY is missing; AI summaries and answers will not work."
        }
        Start-Process $url
        Write-Host "PDF AI Assistant is already running: $url"
        exit 0
    }

    throw "Port 8000 is already in use by another service. Stop that service or change the app port."
}

$pythonCommand = Get-Command python -ErrorAction Stop
$venvDirectory = Join-Path $projectRoot ".venv"
$pythonPath = Join-Path $venvDirectory "Scripts\python.exe"
if (-not (Test-Path $pythonPath)) {
    Write-Host "Creating the project's Python environment..."
    & $pythonCommand.Source -m venv $venvDirectory
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the virtual environment."
    }
}

$requirementsPath = Join-Path $projectRoot "requirements.txt"
$requirementsHash = (Get-FileHash -Path $requirementsPath -Algorithm SHA256).Hash
$markerPath = Join-Path $venvDirectory "requirements.sha256"
$installedHash = if (Test-Path $markerPath) {
    (Get-Content -Path $markerPath -Raw).Trim()
} else {
    ""
}

if ($installedHash -ne $requirementsHash) {
    Write-Host "Installing project requirements. This may take a few minutes..."
    & $pythonPath -m pip install -r $requirementsPath
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed."
    }
    Set-Content -Path $markerPath -Value $requirementsHash -NoNewline
}

$dataDirectory = Join-Path $projectRoot "data"
New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null
$stdoutPath = Join-Path $dataDirectory "server.log"
$stderrPath = Join-Path $dataDirectory "server-error.log"
$server = Start-Process -FilePath $pythonPath `
    -ArgumentList "-m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000" `
    -WorkingDirectory $projectRoot `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -WindowStyle Hidden `
    -PassThru

$ready = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    if ($server.HasExited) {
        break
    }
    try {
        $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
        if ($health.status -eq "ok") {
            $ready = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 1
    }
}

if (-not $ready) {
    throw "The server did not become ready. Check $stderrPath (process ID $($server.Id))."
}

Start-Process $url
Write-Host "PDF AI Assistant is running: $url"
Write-Host "Server process ID: $($server.Id)"
Write-Host "Logs: $stdoutPath"
if (-not $health.llm_configured) {
    Write-Warning "OPENROUTER_API_KEY is missing; AI summaries and answers will not work."
}
