$ErrorActionPreference = "Stop"

Write-Host "== Git status =="
git status

Write-Host "== Backend tests =="
.\.venv\Scripts\python.exe -m pytest -q

Write-Host "== Frontend tests and build =="
Push-Location frontend
try {
    npm test
    npm run build
}
finally {
    Pop-Location
}

Write-Host "== Final verification completed =="
