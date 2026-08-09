# One-time local setup on Windows: venv + Python deps + frontend deps + .env
$ErrorActionPreference = 'Stop'

Set-Location (Join-Path $PSScriptRoot '..')

$python = if ($env:PYTHON) { $env:PYTHON } else { 'python' }
& $python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\pip.exe install -r requirements.txt

Push-Location frontend
npm install
Pop-Location

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host 'Created .env - add your ANTHROPIC_API_KEY.'
}

Write-Host ''
Write-Host 'Setup done. Start the app with two shells:'
Write-Host '  .\.venv\Scripts\uvicorn.exe server:app --reload'
Write-Host '  cd frontend; npm run dev      # http://localhost:5173'
