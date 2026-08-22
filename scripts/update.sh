#!/usr/bin/env bash
#
# update.sh - refresh the Financial Trading AI Orchestrator template in an
# existing project without touching user project code.
#
# Usage:
#   ./scripts/update.sh
#   TEMPLATE_SOURCE_DIR=/path/to/template ./scripts/update.sh
#
# Safety contract:
#   CLAUDE.md and AGENTS.md must exist in both the downstream project and the
#   incoming template. Each contract must contain exactly one full-line start
#   marker and one full-line repository marker, in that order. Missing,
#   duplicated, or misordered markers cause a non-zero exit before any
#   template-managed project content is replaced. If a later replacement
#   fails, private recovery copies are retained and their path is printed.

set -euo pipefail

REPO_URL="${TEMPLATE_REPO_URL:-https://github.com/ohayotaro/claude-finance.git}"
PROJECT_ROOT="$(pwd -P)"
WORK_DIR=""
RECOVERY_DIR=""
MUTATION_STARTED=0
UPDATE_SUCCEEDED=0

red()    { printf "\033[31m%s\033[0m\n" "$*"; }
green()  { printf "\033[32m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }

fail() {
  red "ERROR: $*"
  exit 1
}

cleanup() {
  local status=$?

  trap - EXIT HUP INT TERM
  if [[ "$UPDATE_SUCCEEDED" -eq 1 || "$MUTATION_STARTED" -eq 0 ]]; then
    if [[ -n "$WORK_DIR" && -d "$WORK_DIR" ]]; then
      rm -rf "$WORK_DIR"
    fi
  else
    red "ERROR: Update failed after project replacement began."
    red "Recovery copies were retained at: $RECOVERY_DIR"
  fi
  exit "$status"
}

require_regular_file() {
  local file="$1"

  if [[ ! -f "$file" || -L "$file" ]]; then
    fail "Required regular file is missing or unsafe: $file"
  fi
}

sha256_file() {
  local file="$1"

  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
  else
    fail "Neither shasum nor sha256sum is available for DESIGN.md preservation."
  fi
}

stage_contract() {
  local local_file="$1"
  local template_file="$2"
  local start_marker="$3"
  local repo_marker="$4"
  local output_file="$5"

  python3 - "$local_file" "$template_file" "$start_marker" "$repo_marker" "$output_file" <<'PY'
import sys
from pathlib import Path


def line_content(line):
    if line.endswith(b"\r\n"):
        return line[:-2]
    if line.endswith(b"\n") or line.endswith(b"\r"):
        return line[:-1]
    return line


def marker_indexes(path, lines, marker):
    indexes = [index for index, line in enumerate(lines) if line_content(line) == marker]
    if len(indexes) != 1:
        marker_text = marker.decode("ascii")
        raise ValueError(
            f"{path}: expected exactly one full-line marker {marker_text!r}; "
            f"found {len(indexes)}"
        )
    return indexes[0]


def validated_lines(path, start_marker, repo_marker):
    lines = path.read_bytes().splitlines(keepends=True)
    start_index = marker_indexes(path, lines, start_marker)
    repo_index = marker_indexes(path, lines, repo_marker)
    if start_index >= repo_index:
        raise ValueError(
            f"{path}: marker {start_marker.decode('ascii')!r} must precede "
            f"{repo_marker.decode('ascii')!r}"
        )
    return lines, start_index, repo_index


local_path = Path(sys.argv[1])
template_path = Path(sys.argv[2])
start = sys.argv[3].encode("ascii")
repo = sys.argv[4].encode("ascii")
output_path = Path(sys.argv[5])

try:
    local_lines, local_start, local_repo = validated_lines(local_path, start, repo)
    template_lines, template_start, template_repo = validated_lines(
        template_path, start, repo
    )
except ValueError as error:
    print(f"[update.sh] ERROR: {error}", file=sys.stderr)
    raise SystemExit(1)

composed = b"".join(
    template_lines[: template_start + 1]
    + local_lines[local_start + 1 : local_repo]
    + template_lines[template_repo : template_repo + 1]
    + local_lines[local_repo + 1 :]
)
output_path.write_bytes(composed)
PY
}

backup_for_recovery() {
  local target="$1"
  local destination_parent

  destination_parent="$RECOVERY_DIR/project/$(dirname "$target")"

  if [[ -e "$target" || -L "$target" ]]; then
    mkdir -p "$destination_parent"
    cp -pR "$target" "$destination_parent/"
  else
    printf '%s\n' "$target" >> "$RECOVERY_DIR/originally-absent.txt"
  fi
}

if [[ ! -d ".claude" || -L ".claude" ]]; then
  fail "No safe .claude/ directory found. Run this from an installed project root."
fi
require_regular_file "CLAUDE.md"
require_regular_file "AGENTS.md"

umask 077
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/claude-finance-update.XXXXXX")"
chmod 700 "$WORK_DIR"
RECOVERY_DIR="$WORK_DIR/recovery"
mkdir -p "$RECOVERY_DIR/project"
trap cleanup EXIT HUP INT TERM

if [[ -n "${TEMPLATE_SOURCE_DIR:-}" ]]; then
  [[ -d "$TEMPLATE_SOURCE_DIR" ]] || fail "Template source is not a directory: $TEMPLATE_SOURCE_DIR"
  TEMPLATE_DIR="$(cd "$TEMPLATE_SOURCE_DIR" && pwd -P)"
  [[ "$TEMPLATE_DIR" != "$PROJECT_ROOT" ]] || fail "Template source must differ from the downstream project root."
  yellow "Using local template source: $TEMPLATE_DIR"
else
  TEMPLATE_DIR="$WORK_DIR/template"
  yellow "Cloning latest template into private temporary storage"
  git clone --depth 1 "$REPO_URL" "$TEMPLATE_DIR"
fi

[[ -d "$TEMPLATE_DIR/.claude" && ! -L "$TEMPLATE_DIR/.claude" ]] || \
  fail "Incoming template has no safe .claude/ directory: $TEMPLATE_DIR/.claude"
require_regular_file "$TEMPLATE_DIR/CLAUDE.md"
require_regular_file "$TEMPLATE_DIR/AGENTS.md"

yellow "Preflighting and staging protected contract sections"
stage_contract \
  "CLAUDE.md" \
  "$TEMPLATE_DIR/CLAUDE.md" \
  "@orchestra:template-boundary" \
  "@orchestra:repo-boundary" \
  "$WORK_DIR/CLAUDE.md"
stage_contract \
  "AGENTS.md" \
  "$TEMPLATE_DIR/AGENTS.md" \
  "@codex:template-boundary" \
  "@codex:repo-boundary" \
  "$WORK_DIR/AGENTS.md"

THRESHOLDS_BACKUP="$WORK_DIR/backtest-thresholds.json"
if [[ -f ".claude/backtest-thresholds.json" && ! -L ".claude/backtest-thresholds.json" ]]; then
  yellow "Staging .claude/backtest-thresholds.json"
  cp ".claude/backtest-thresholds.json" "$THRESHOLDS_BACKUP"
elif [[ -e ".claude/backtest-thresholds.json" || -L ".claude/backtest-thresholds.json" ]]; then
  fail "Unsafe local threshold path: .claude/backtest-thresholds.json"
fi

DESIGN_BACKUP="$WORK_DIR/DESIGN.md"
DESIGN_ARCHIVE_PATH=""
if [[ -f "$TEMPLATE_DIR/.claude/docs/DESIGN.md" ]]; then
  [[ ! -L "$TEMPLATE_DIR/.claude/docs/DESIGN.md" ]] || \
    fail "Unsafe incoming DESIGN.md symlink."
  if [[ -f ".claude/docs/DESIGN.md" && ! -L ".claude/docs/DESIGN.md" ]]; then
    if ! cmp -s ".claude/docs/DESIGN.md" "$TEMPLATE_DIR/.claude/docs/DESIGN.md"; then
      cp ".claude/docs/DESIGN.md" "$DESIGN_BACKUP"
      DESIGN_DIGEST="$(sha256_file "$DESIGN_BACKUP")"
      DESIGN_ARCHIVE_PATH=".claude/docs/DESIGN.local-preserved.sha256-${DESIGN_DIGEST}.md"
      if [[ -e "$DESIGN_ARCHIVE_PATH" || -L "$DESIGN_ARCHIVE_PATH" ]]; then
        if [[ ! -f "$DESIGN_ARCHIVE_PATH" || -L "$DESIGN_ARCHIVE_PATH" ]]; then
          fail "Unsafe DESIGN.md archive path: $DESIGN_ARCHIVE_PATH"
        fi
        cmp -s "$DESIGN_BACKUP" "$DESIGN_ARCHIVE_PATH" || \
          fail "DESIGN.md archive digest collision or content mismatch: $DESIGN_ARCHIVE_PATH"
      fi
    fi
  elif [[ -e ".claude/docs/DESIGN.md" || -L ".claude/docs/DESIGN.md" ]]; then
    fail "Unsafe local DESIGN.md path."
  fi
fi

if [[ -e ".claude/docs" || -L ".claude/docs" ]]; then
  [[ -d ".claude/docs" && ! -L ".claude/docs" ]] || fail "Unsafe local .claude/docs path."
fi

yellow "Creating private recovery copies"
RECOVERY_TARGETS=(
  "CLAUDE.md"
  "AGENTS.md"
  ".claude/agents"
  ".claude/routing-keywords.json"
  ".gemini"
  ".claude/hooks"
  ".claude/rules"
  ".claude/skills"
  ".claude/scripts"
  ".claude/settings.json"
  ".claude/backtest-thresholds.json"
  ".claude/docs/CODEX_TASK_CONTRACT.md"
  ".claude/docs/DESIGN.md"
  ".codex"
)
for target in "${RECOVERY_TARGETS[@]}"; do
  backup_for_recovery "$target"
done
printf '%s\n' \
  "These files are private recovery copies from a failed template update." \
  "Copy only the needed paths back into the downstream project after inspection." \
  > "$RECOVERY_DIR/README.txt"

MUTATION_STARTED=1

yellow "Removing legacy provider and routing paths"
rm -rf ".claude/agents" ".claude/routing-keywords.json" ".gemini"

TEMPLATE_DIRS_IN_CLAUDE=(hooks rules skills scripts)
TEMPLATE_FILES_IN_CLAUDE=(
  settings.json
  backtest-thresholds.json
  docs/CODEX_TASK_CONTRACT.md
  docs/DESIGN.md
)

yellow "Replacing template-managed .claude paths"
for directory in "${TEMPLATE_DIRS_IN_CLAUDE[@]}"; do
  if [[ -d "$TEMPLATE_DIR/.claude/$directory" ]]; then
    rm -rf ".claude/$directory"
    cp -R "$TEMPLATE_DIR/.claude/$directory" ".claude/$directory"
  fi
done

if [[ -n "$DESIGN_ARCHIVE_PATH" ]]; then
  mkdir -p ".claude/docs"
  if [[ ! -e "$DESIGN_ARCHIVE_PATH" && ! -L "$DESIGN_ARCHIVE_PATH" ]]; then
    cp -n "$DESIGN_BACKUP" "$DESIGN_ARCHIVE_PATH"
  fi
  [[ -f "$DESIGN_ARCHIVE_PATH" && ! -L "$DESIGN_ARCHIVE_PATH" ]] || \
    fail "DESIGN.md archive was not created safely: $DESIGN_ARCHIVE_PATH"
  cmp -s "$DESIGN_BACKUP" "$DESIGN_ARCHIVE_PATH" || \
    fail "DESIGN.md archive verification failed: $DESIGN_ARCHIVE_PATH"
fi

for file in "${TEMPLATE_FILES_IN_CLAUDE[@]}"; do
  if [[ -f "$TEMPLATE_DIR/.claude/$file" ]]; then
    mkdir -p "$(dirname ".claude/$file")"
    cp "$TEMPLATE_DIR/.claude/$file" ".claude/$file"
  fi
done

yellow "Replacing root contracts and Codex config"
cp "$WORK_DIR/CLAUDE.md" "CLAUDE.md"
cp "$WORK_DIR/AGENTS.md" "AGENTS.md"
if [[ -d "$TEMPLATE_DIR/.codex" ]]; then
  rm -rf ".codex"
  cp -R "$TEMPLATE_DIR/.codex" ".codex"
fi

if [[ -f "$THRESHOLDS_BACKUP" ]]; then
  cp "$THRESHOLDS_BACKUP" ".claude/backtest-thresholds.json"
fi

chmod +x .claude/hooks/*.py .claude/scripts/*.py 2>/dev/null || true

UPDATE_SUCCEEDED=1
green "Update complete."
yellow "Next steps:"
printf '%s\n' \
  "  - Review changes: git diff" \
  "  - Run: uv sync --extra dev" \
  "  - Run: uv run --extra dev pytest -m \"not integration and not slow\""
