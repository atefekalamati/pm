# Stops Tidy and removes its container (Windows). The database volume is kept.
Push-Location (Join-Path $PSScriptRoot "..")
try {
    docker compose down
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "Tidy has stopped."
}
finally {
    Pop-Location
}
