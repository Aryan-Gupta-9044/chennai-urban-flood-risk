# One-command setup + pipeline for Windows 11 (PowerShell 5.1+).
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1
# Optional:  -Only "B,C"   (run just some modules)
param([string]$Only = "")
$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
New-Item -ItemType Directory -Force -Path logs | Out-Null
$setupLog = Join-Path $PSScriptRoot "logs\setup.log"
function Say($m) { Write-Host $m; Add-Content -Path $setupLog -Value ("{0} {1}" -f (Get-Date -Format "HH:mm:ss"), $m) }

Say "=== Chennai flood-risk: setup and run ==="

# 1. Find a suitable Python (3.10 - 3.13)
$pyExe = $null; $pyArgs = @()
$candidates = @(
    @{ exe = "py";      args = @("-3.12") }, @{ exe = "py"; args = @("-3.11") }, @{ exe = "py"; args = @("-3.13") },
    @{ exe = "py";      args = @("-3.10") }, @{ exe = "python"; args = @() },  @{ exe = "python3"; args = @() }
)
foreach ($c in $candidates) {
    if (-not (Get-Command $c.exe -ErrorAction SilentlyContinue)) { continue }
    $v = & $c.exe @($c.args) -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($LASTEXITCODE -eq 0 -and $v -match '^3\.(1[0-3])$') { $pyExe = $c.exe; $pyArgs = @($c.args); Say "Using Python $v ($($c.exe) $($c.args -join ' '))"; break }
}
if (-not $pyExe) {
    Say "ERROR: Python 3.10-3.13 not found. Install Python 3.12 from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then re-run."
    exit 1
}

# 2. Virtual environment
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Say "Creating virtual environment .venv ..."
    & $pyExe @($pyArgs) -m venv .venv
    if (-not (Test-Path $venvPy)) { Say "ERROR: could not create .venv"; exit 1 }
} else { Say "Existing .venv found." }

# 3. Install dependencies only if requirements.txt changed
$hash = (Get-FileHash requirements.txt -Algorithm SHA256).Hash
$hashFile = Join-Path $PSScriptRoot ".venv\requirements.sha256"
$old = if (Test-Path $hashFile) { (Get-Content $hashFile -Raw).Trim() } else { "" }
if ($old -ne $hash) {
    Say "Installing dependencies (first run takes a few minutes) ..."
    & $venvPy -m pip install --upgrade pip 2>&1 | Tee-Object -FilePath $setupLog -Append | Out-Null
    & $venvPy -m pip install -r requirements.txt 2>&1 | Tee-Object -FilePath $setupLog -Append | ForEach-Object { if ($_ -match "ERROR|Successfully") { Write-Host $_ } }
    if ($LASTEXITCODE -ne 0) { Say "ERROR: pip install failed. See logs\setup.log. (Check your internet connection and retry.)"; exit 1 }
    Set-Content -Path $hashFile -Value $hash
} else { Say "Dependencies already installed (requirements.txt unchanged)." }

# 4. Run the pipeline (each module is isolated; failures are reported, not fatal)
$args2 = @("scripts\run_pipeline.py"); if ($Only) { $args2 += @("--only", $Only) }
& $venvPy @args2
$rc = $LASTEXITCODE

$report = Join-Path $PSScriptRoot "outputs\reports\implementation_summary.html"
if (Test-Path $report) { Say "Opening report: $report"; Start-Process $report }
Say ""
Say "To view the dashboard:   .\.venv\Scripts\streamlit run dashboard\app.py"
exit $rc
