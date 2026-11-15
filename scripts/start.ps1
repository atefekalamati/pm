# Builds and starts Tidy in Docker (Windows).
Push-Location (Join-Path $PSScriptRoot "..")
try {
    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Docker is not running. Start Docker Desktop and try again."
        exit 1
    }

    if (-not (Test-Path .env)) {
        Write-Host "No .env file found: Tidy will run without AI. Copy .env.example to .env to enable it."
    }

    docker compose up -d --build --wait
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "Tidy is running at http://localhost:8000"
}
finally {
    Pop-Location
}
