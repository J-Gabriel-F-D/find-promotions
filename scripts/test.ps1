param(
    [ValidateSet("test", "unit", "integration", "e2e", "security", "functional", "regression", "coverage", "all")]
    [string]$Target = "test"
)

$ErrorActionPreference = "Stop"
$python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }

function Invoke-Step {
    param([string]$Label, [scriptblock]$Command)
    Write-Host "==> $Label" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Falhou: $Label" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

function Invoke-Pytest {
    param([string[]]$Arguments)
    Invoke-Step "pytest $($Arguments -join ' ')" { & $python -m pytest @Arguments }
}

switch ($Target) {
    "test" { Invoke-Pytest @("tests") }
    "unit" { Invoke-Pytest @("tests/unit") }
    "integration" { Invoke-Pytest @("-m", "integration") }
    "e2e" { Invoke-Pytest @("-m", "e2e") }
    "functional" { Invoke-Pytest @("-m", "functional") }
    "regression" { Invoke-Pytest @("-m", "regression") }
    "security" { Invoke-Pytest @("-m", "security") }
    "coverage" {
        Invoke-Pytest @("--cov=dealhunter", "--cov-report=term-missing", "--cov-report=xml")
    }
    "all" {
        Invoke-Step "ruff format --check" { & $python -m ruff format --check src tests }
        Invoke-Step "ruff check" { & $python -m ruff check src tests }
        Invoke-Step "mypy" { & $python -m mypy src }
        Invoke-Step "bandit" { & $python -m bandit -q -r src }
        Invoke-Step "detect-secrets" { & $python -m detect_secrets scan src }
        Invoke-Step "pip-audit" { & $python -m pip_audit --skip-editable }
        Invoke-Pytest @("--cov=dealhunter", "--cov-report=term-missing", "--cov-report=xml")
    }
}
