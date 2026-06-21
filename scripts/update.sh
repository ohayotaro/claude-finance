#!/usr/bin/env bash
#
# update.sh — refresh the Financial Trading AI Orchestrator template in an
# existing project without touching user project code.
#
# Usage:
#   ./scripts/update.sh
#   TEMPLATE_SOURCE_DIR=/path/to/template ./scripts/update.sh

set -euo pipefail

REPO_URL="${TEMPLATE_REPO_URL:-https://github.com/ohayotaro/claude-finance.git}"
TMP_DIR=".starter-update"
BACKUP_ZONE_B=".zone-b.backup.md"
BACKUP_AGENTS_PROJECT=".agents-project.backup.md"
BACKUP_THRESHOLDS=".backtest-thresholds.backup.json"
BACKUP_DESIGN=".design-local.backup.md"

red()    { printf "\033[31m%s\033[0m\n" "$*"; }
green()  { printf "\033[32m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }

require_file() {
  if [[ ! -f "$1" ]]; then
    red "Missing $1 — run this from an installed project root."
    exit 1
  fi
}

extract_between_markers() {
  local file="$1"
  local start="$2"
  local end="$3"
  local output="$4"

  if [[ ! -f "$file" ]]; then
    : > "$output"
    return
  fi

  awk -v start="$start" -v end="$end" '
    $0 ~ start { in_zone=1; next }
    $0 ~ end   { in_zone=0; next }
    in_zone { print }
  ' "$file" > "$output"
}

restore_between_markers() {
  local file="$1"
  local start="$2"
  local end="$3"
  local backup="$4"

  if [[ ! -s "$backup" || ! -f "$file" ]]; then
    return
  fi

  python3 - "$file" "$start" "$end" "$backup" <<'PY'
import sys
from pathlib import Path

target = Path(sys.argv[1])
start = sys.argv[2]
end = sys.argv[3]
backup = Path(sys.argv[4]).read_text(encoding="utf-8")
text = target.read_text(encoding="utf-8")
i = text.find(start)
j = text.find(end)
if i == -1 or j == -1:
    print(f"[update.sh] {target} missing boundary markers; restore skipped", file=sys.stderr)
    raise SystemExit(0)
i_eol = text.find("\n", i)
new_text = text[: i_eol + 1] + "\n" + backup.rstrip("\n") + "\n\n" + text[j:]
target.write_text(new_text, encoding="utf-8")
PY
}

if [[ ! -d ".claude" ]]; then
  red "No .claude/ here. Run this from the project root that already has the template installed."
  exit 1
fi
require_file "CLAUDE.md"

yellow "Backing up CLAUDE.md Zone B"
extract_between_markers \
  "CLAUDE.md" \
  "@orchestra:template-boundary" \
  "@orchestra:repo-boundary" \
  "$BACKUP_ZONE_B"

yellow "Backing up AGENTS.md project section"
extract_between_markers \
  "AGENTS.md" \
  "@codex:template-boundary" \
  "@codex:repo-boundary" \
  "$BACKUP_AGENTS_PROJECT"

if [[ -f ".claude/backtest-thresholds.json" ]]; then
  yellow "Backing up .claude/backtest-thresholds.json"
  cp ".claude/backtest-thresholds.json" "$BACKUP_THRESHOLDS"
fi

if [[ -f ".claude/docs/DESIGN.md" ]]; then
  cp ".claude/docs/DESIGN.md" "$BACKUP_DESIGN"
fi

if [[ -n "${TEMPLATE_SOURCE_DIR:-}" ]]; then
  TEMPLATE_DIR="$TEMPLATE_SOURCE_DIR"
  yellow "Using local template source: $TEMPLATE_DIR"
else
  yellow "Cloning latest template into $TMP_DIR/"
  rm -rf "$TMP_DIR"
  git clone --depth 1 "$REPO_URL" "$TMP_DIR"
  TEMPLATE_DIR="$TMP_DIR"
fi

yellow "Removing legacy provider and routing paths"
rm -rf .claude/agents .claude/routing-keywords.json .gemini

TEMPLATE_DIRS_IN_CLAUDE=(hooks rules skills scripts)
TEMPLATE_FILES_IN_CLAUDE=(
  settings.json
  backtest-thresholds.json
  docs/CODEX_TASK_CONTRACT.md
  docs/DESIGN.md
)

yellow "Replacing template-managed .claude paths"
for d in "${TEMPLATE_DIRS_IN_CLAUDE[@]}"; do
  rm -rf ".claude/$d"
  if [[ -d "$TEMPLATE_DIR/.claude/$d" ]]; then
    mkdir -p ".claude"
    cp -R "$TEMPLATE_DIR/.claude/$d" ".claude/$d"
  fi
done

for f in "${TEMPLATE_FILES_IN_CLAUDE[@]}"; do
  if [[ -f "$TEMPLATE_DIR/.claude/$f" ]]; then
    mkdir -p "$(dirname ".claude/$f")"
    cp "$TEMPLATE_DIR/.claude/$f" ".claude/$f"
  fi
done

if [[ -f "$BACKUP_DESIGN" ]]; then
  mkdir -p ".claude/docs"
  cp "$BACKUP_DESIGN" ".claude/docs/DESIGN.local-preserved.md"
fi

yellow "Replacing root contracts and Codex config"
cp "$TEMPLATE_DIR/CLAUDE.md" CLAUDE.md
if [[ -f "$TEMPLATE_DIR/AGENTS.md" ]]; then
  cp "$TEMPLATE_DIR/AGENTS.md" AGENTS.md
fi
rm -rf .codex
if [[ -d "$TEMPLATE_DIR/.codex" ]]; then
  cp -R "$TEMPLATE_DIR/.codex" .codex
fi

yellow "Restoring preserved local sections"
restore_between_markers \
  "CLAUDE.md" \
  "@orchestra:template-boundary" \
  "@orchestra:repo-boundary" \
  "$BACKUP_ZONE_B"

restore_between_markers \
  "AGENTS.md" \
  "@codex:template-boundary" \
  "@codex:repo-boundary" \
  "$BACKUP_AGENTS_PROJECT"

if [[ -f "$BACKUP_THRESHOLDS" ]]; then
  mv "$BACKUP_THRESHOLDS" ".claude/backtest-thresholds.json"
fi

chmod +x .claude/hooks/*.py .claude/scripts/*.py 2>/dev/null || true

if [[ -z "${TEMPLATE_SOURCE_DIR:-}" ]]; then
  rm -rf "$TMP_DIR"
fi
rm -f "$BACKUP_ZONE_B" "$BACKUP_AGENTS_PROJECT" "$BACKUP_THRESHOLDS" "$BACKUP_DESIGN"

green "Update complete."
yellow "Next steps:"
echo "  - Review changes: git diff"
echo "  - Run: uv sync --extra dev"
echo "  - Run: uv run --extra dev pytest -m \"not integration and not slow\""
