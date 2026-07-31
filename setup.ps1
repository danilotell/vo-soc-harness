#!/usr/bin/env pwsh
# ---------------------------------------------------------------------------
# Turnkey setup for the Custom Vision One MCP server (Windows / PowerShell).
# Installs uv (if needed), provisions Python, creates the venv, installs deps,
# and seeds the .env file. After this, just fill in credentials and run.
# ---------------------------------------------------------------------------
$ErrorActionPreference = "Stop"
Set-Location -Path (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host "==> Custom Vision One MCP — setup" -ForegroundColor Cyan

# 1. Ensure uv is installed
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "==> Installing uv..." -ForegroundColor Yellow
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
uv --version

# 2. Create the virtual environment and install dependencies.
#    uv ignores system interpreters and downloads the version in `.python-version`.
Write-Host "==> Creating virtual environment and installing dependencies..." -ForegroundColor Cyan
uv sync --directory mcp_server

# 3. Seed the .env file from the example (never overwrite an existing one)
$envFile = "mcp_server/src/.env"
$envExample = "mcp_server/src/.env.example"
if (-not (Test-Path $envFile)) {
    Copy-Item $envExample $envFile
    Write-Host "==> Created $envFile — fill in your credentials." -ForegroundColor Green
} else {
    Write-Host "==> $envFile already exists; leaving it untouched." -ForegroundColor DarkGray
}

# 4. Seed the harness state files (runtime data, not versioned). The seeds carry
#    the canonical empty SHAPE, so an agent never has to invent it.
Write-Host "==> Seeding harness state files..." -ForegroundColor Cyan
$seeds = @{
    "workbench_list.json"          = "docs/references/seed_workbench_list.json"
    "context/alert_context.json"   = "docs/references/seed_alert_context.json"
    "memory/history.json"          = "docs/references/seed_history.json"
    "progress/current.md"          = "docs/references/seed_progress.md"
}
foreach ($target in $seeds.Keys) {
    if (-not (Test-Path $target)) {
        $parent = Split-Path -Parent $target
        if ($parent -and -not (Test-Path $parent)) {
            New-Item -ItemType Directory -Force $parent | Out-Null
        }
        Copy-Item $seeds[$target] $target
        Write-Host "    created $target" -ForegroundColor Green
    }
}

# 5. Runtime directories that hold no seeded file, so the loop above does not
#    create them. Creating them here keeps the harness from depending on an agent
#    doing it, and lets MCP_AUDIT_LOG_FILE be enabled by uncommenting one line.
Write-Host "==> Creating runtime directories..." -ForegroundColor Cyan
foreach ($dir in @("docs/reports/outputs", "audit")) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force $dir | Out-Null
        Write-Host "    created $dir/" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  1. Edit mcp_server/src/.env with your credentials."
Write-Host "  2. Run the server:  uv run --directory mcp_server python src/custom_vo_mcp.py"
Write-Host "  (OpenCode launches it automatically via .opencode/opencode.json.)"
