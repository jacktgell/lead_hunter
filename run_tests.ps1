# run_tests.ps1
# Senior Standard: "Always Green" Runner (No Coverage Threshold)

Write-Host "Initializing Lead Hunter Test Suite..." -ForegroundColor Cyan

# 1. Dependency Check
$hasPytest = Get-Command pytest -ErrorAction SilentlyContinue
if (-not $hasPytest) {
    Write-Host "Installing dependencies..." -ForegroundColor Gray
    pip install pytest pytest-cov hypothesis -q
}

# 2. Path Injection
$env:PYTHONPATH = "."
$env:PYTEST_ADDOPTS = "--color=yes"

# 3. Execution
Write-Host "Running verification suite..." -ForegroundColor Yellow
pytest -v --cov=application --cov=infrastructure --cov=core --cov=domain --cov-report=term-missing tests/

# 4. Handle Results
$exit = $LASTEXITCODE
if ($exit -eq 0) {
    Write-Host "SUCCESS: All tests passed." -ForegroundColor Green
} else {
    Write-Host "FAILURE: Check test errors above." -ForegroundColor Red
    exit $exit
}