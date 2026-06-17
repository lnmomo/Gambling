$ErrorActionPreference = "Stop"

Write-Host "== Backend tests =="
.\.venv\Scripts\python.exe -m pytest -q

Write-Host "== Frontend tests =="
Push-Location frontend
try {
    npm test
}
finally {
    Pop-Location
}
