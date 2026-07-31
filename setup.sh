#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Turnkey setup for the Custom Vision One MCP server (Linux / macOS).
# Installs uv (if needed), provisions Python, creates the venv, installs deps,
# and seeds the .env file. After this, just fill in credentials and run.
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Custom Vision One MCP — setup"

# 1. Ensure uv is installed
if ! command -v uv >/dev/null 2>&1; then
    echo "==> Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
uv --version

# 2. Create the virtual environment and install dependencies.
#    uv ignores system interpreters and downloads the version in `.python-version`.
echo "==> Creating virtual environment and installing dependencies..."
uv sync --directory mcp_server

# 3. Seed the .env file from the example (never overwrite an existing one)
ENV_FILE="mcp_server/src/.env"
ENV_EXAMPLE="mcp_server/src/.env.example"
if [ ! -f "$ENV_FILE" ]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    echo "==> Created $ENV_FILE — fill in your credentials."
else
    echo "==> $ENV_FILE already exists; leaving it untouched."
fi

# 4. Seed the harness state files (runtime data, not versioned). The seeds carry
#    the canonical empty SHAPE, so an agent never has to invent it.
echo "==> Seeding harness state files..."
while IFS='|' read -r seed target; do
    if [ ! -f "$target" ]; then
        mkdir -p "$(dirname "$target")"
        cp "docs/references/$seed" "$target"
        echo "    created $target"
    fi
done <<'SEEDS'
seed_workbench_list.json|workbench_list.json
seed_alert_context.json|context/alert_context.json
seed_history.json|memory/history.json
seed_progress.md|progress/current.md
SEEDS

# 5. Runtime directories that hold no seeded file, so the loop above does not
#    create them. Creating them here keeps the harness from depending on an agent
#    doing it, and lets MCP_AUDIT_LOG_FILE be enabled by uncommenting one line.
echo "==> Creating runtime directories..."
for dir in docs/reports/outputs audit; do
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir"
        echo "    created $dir/"
    fi
done

echo ""
echo "Done."
echo "Next steps:"
echo "  1. Edit mcp_server/src/.env with your credentials."
echo "  2. Run the server:  uv run --directory mcp_server python src/custom_vo_mcp.py"
echo "  (OpenCode launches it automatically via .opencode/opencode.json.)"
