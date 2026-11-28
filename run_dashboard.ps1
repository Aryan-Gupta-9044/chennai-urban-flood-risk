# Start the unified Chennai flood-risk dashboard (FINAL-01).
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\run_dashboard.ps1
Set-Location -Path $PSScriptRoot
$env:PYTHONUTF8 = "1"
$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Host "ERROR: .venv not found. Run .\run.ps1 once first."; exit 1 }
& $py -c "import streamlit, folium, altair" 2>$null
if ($LASTEXITCODE -ne 0) { & $py -m pip install -r requirements-dashboard.txt }
& $py -m streamlit run dashboard\app.py --server.headless false
