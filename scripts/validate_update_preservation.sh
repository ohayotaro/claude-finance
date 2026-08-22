#!/usr/bin/env bash
#
# Validate the Python updater and its shell entry point using isolated offline
# fixtures. Expected output is one PASS line; failures print ERROR and exit.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
PYTHON_UPDATER="$SCRIPT_DIR/update.py"
SHELL_UPDATER="$SCRIPT_DIR/update.sh"
FIXTURE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/validate-update-preservation.XXXXXX")"
NO_NETWORK_BIN="$FIXTURE_ROOT/no-network-bin"
PYTHON=""

cleanup() {
  local status=$?

  trap - EXIT HUP INT TERM
  rm -rf "$FIXTURE_ROOT"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

assert_same() {
  local expected="$1"
  local actual="$2"
  local description="$3"

  cmp -s "$expected" "$actual" || fail "$description differs: $actual"
}

assert_tree_same() {
  local expected="$1"
  local actual="$2"
  local description="$3"

  diff -r "$expected" "$actual" >/dev/null || fail "$description differs"
}

sha256_file() {
  local file="$1"

  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
  else
    fail "Neither shasum nor sha256sum is available."
  fi
}

is_supported_python() {
  "$1" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' \
    >/dev/null 2>&1
}

resolve_python() {
  local candidate

  if [[ -n "${UPDATER_PYTHON:-}" ]] && is_supported_python "$UPDATER_PYTHON"; then
    printf '%s\n' "$UPDATER_PYTHON"
    return 0
  fi

  for candidate in python3 python python3.14 python3.13 python3.12 python3.11; do
    if command -v "$candidate" >/dev/null 2>&1; then
      candidate="$(command -v "$candidate")"
      if is_supported_python "$candidate"; then
        printf '%s\n' "$candidate"
        return 0
      fi
    fi
  done

  if command -v uv >/dev/null 2>&1; then
    candidate="$(uv python find '>=3.11' 2>/dev/null || true)"
    if [[ -n "$candidate" ]] && is_supported_python "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  fi

  return 1
}

if PYTHON="$(resolve_python)"; then
  :
else
  fail "Python 3.11 or newer is required. Set UPDATER_PYTHON, install a supported interpreter, or ensure uv can find one."
fi

make_template() {
  local root="$1"

  mkdir -p \
    "$root/.claude/hooks" \
    "$root/.claude/rules" \
    "$root/.claude/skills" \
    "$root/.claude/scripts" \
    "$root/.claude/docs" \
    "$root/.codex" \
    "$root/scripts"

  {
    printf '# Incoming CLAUDE\r\n'
    printf 'Prose containing @orchestra:template-boundary is not a marker.\r\n'
    printf '@orchestra:template-boundary\r\n'
    printf 'Incoming Zone B.\n'
    printf '@orchestra:repo-boundary\r\n'
    printf 'Incoming Zone C without newline.'
  } > "$root/CLAUDE.md"
  {
    printf '# Incoming AGENTS\n'
    printf 'Prose containing @codex:repo-boundary is not a marker.\n'
    printf '@codex:template-boundary\n'
    printf 'Incoming project section.\n'
    printf '@codex:repo-boundary\n'
    printf 'Incoming post-boundary section.\n'
  } > "$root/AGENTS.md"

  printf '%s\n' 'incoming hook' > "$root/.claude/hooks/example.py"
  printf '%s\n' 'incoming rule' > "$root/.claude/rules/example.md"
  printf '%s\n' 'incoming skill' > "$root/.claude/skills/example.md"
  printf '%s\n' 'incoming script' > "$root/.claude/scripts/example.py"
  printf '%s\n' '{"incoming": true}' > "$root/.claude/settings.json"
  printf '%s\n' '{"threshold": "incoming"}' > "$root/.claude/backtest-thresholds.json"
  printf '%s\n' 'incoming task contract' > "$root/.claude/docs/CODEX_TASK_CONTRACT.md"
  printf '%s\n' 'incoming design' > "$root/.claude/docs/DESIGN.md"
  printf '%s\n' 'incoming codex config' > "$root/.codex/config.toml"
  cp "$PYTHON_UPDATER" "$root/scripts/update.py"
  cp "$SCRIPT_DIR/validate_update_preservation.sh" \
    "$root/scripts/validate_update_preservation.sh"
  cp "$SHELL_UPDATER" "$root/scripts/update.sh"
}

make_downstream() {
  local root="$1"

  mkdir -p \
    "$root/.claude/agents" \
    "$root/.claude/hooks" \
    "$root/.claude/rules" \
    "$root/.claude/skills" \
    "$root/.claude/scripts" \
    "$root/.claude/docs" \
    "$root/.claude/tasks/task-1" \
    "$root/.claude/logs" \
    "$root/.gemini" \
    "$root/.codex" \
    "$root/scripts"

  {
    printf '# Local CLAUDE\n'
    printf '@orchestra:template-boundary\n'
    printf 'Local Zone B one.\n'
    printf 'Embedded @orchestra:repo-boundary text remains content.\r\n'
    printf '@orchestra:repo-boundary\r\n'
    printf 'Local Zone C one.\r'
    printf 'Embedded @orchestra:template-boundary text remains content.\n'
    printf 'Local Zone C final without newline.'
  } > "$root/CLAUDE.md"
  {
    printf '# Local AGENTS\r\n'
    printf '@codex:template-boundary\r\n'
    printf 'Local project section.\r\n'
    printf 'Embedded @codex:repo-boundary remains content.\n'
    printf '@codex:repo-boundary\n'
    printf 'Local post-boundary section without newline.'
  } > "$root/AGENTS.md"

  printf '%s\n' 'legacy agent' > "$root/.claude/agents/old.md"
  printf '%s\n' '{}' > "$root/.claude/routing-keywords.json"
  printf '%s\n' '{}' > "$root/.gemini/settings.json"
  printf '%s\n' 'local hook' > "$root/.claude/hooks/local.py"
  printf '%s\n' 'local rule' > "$root/.claude/rules/local.md"
  printf '%s\n' 'local skill' > "$root/.claude/skills/local.md"
  printf '%s\n' 'local script' > "$root/.claude/scripts/local.py"
  printf '%s\n' '{"local": true}' > "$root/.claude/settings.json"
  printf '%s\n' '{"threshold": "local"}' > "$root/.claude/backtest-thresholds.json"
  printf '%s\n' 'local task contract' > "$root/.claude/docs/CODEX_TASK_CONTRACT.md"
  printf 'local design without newline' > "$root/.claude/docs/DESIGN.md"
  printf '%s\n' 'legacy archive unchanged' > \
    "$root/.claude/docs/DESIGN.local-preserved.md"
  printf '%s\n' 'preserved task' > "$root/.claude/tasks/task-1/brief.md"
  printf '%s\n' 'preserved log' > "$root/.claude/logs/preserved.log"
  printf '%s\n' 'local codex config' > "$root/.codex/config.toml"
  printf '%s\n' 'stale updater' > "$root/scripts/update.py"
  printf '%s\n' 'stale updater' > "$root/scripts/validate_update_preservation.sh"
  printf '%s\n' 'stale updater' > "$root/scripts/update.sh"
  printf '%s\n' 'project owned' > "$root/scripts/project-owned-decoy.sh"

  for old_backup in \
    .zone-b.backup.md \
    .agents-project.backup.md \
    .backtest-thresholds.backup.json \
    .design-local.backup.md
  do
    printf '%s\n' "reserved sentinel $old_backup" > "$root/$old_backup"
  done
}

make_expected_contracts() {
  local root="$1"

  mkdir -p "$root"
  {
    printf '# Incoming CLAUDE\r\n'
    printf 'Prose containing @orchestra:template-boundary is not a marker.\r\n'
    printf '@orchestra:template-boundary\r\n'
    printf 'Local Zone B one.\n'
    printf 'Embedded @orchestra:repo-boundary text remains content.\r\n'
    printf '@orchestra:repo-boundary\r\n'
    printf 'Local Zone C one.\r'
    printf 'Embedded @orchestra:template-boundary text remains content.\n'
    printf 'Local Zone C final without newline.'
  } > "$root/CLAUDE.md"
  {
    printf '# Incoming AGENTS\n'
    printf 'Prose containing @codex:repo-boundary is not a marker.\n'
    printf '@codex:template-boundary\n'
    printf 'Local project section.\r\n'
    printf 'Embedded @codex:repo-boundary remains content.\n'
    printf '@codex:repo-boundary\n'
    printf 'Local post-boundary section without newline.'
  } > "$root/AGENTS.md"
}

run_update() {
  local entry_point="$1"
  local project="$2"
  local template="$3"
  local log_file="$4"

  if [[ "$entry_point" = "python" ]]; then
    set -- "$PYTHON" "$PYTHON_UPDATER"
  else
    set -- "$SHELL_UPDATER"
  fi
  if ! (
    cd "$project"
    PATH="$NO_NETWORK_BIN:$PATH" \
      TEMPLATE_REPO_URL="network-clone-must-not-run" \
      TEMPLATE_SOURCE_DIR="$template" \
      "$@"
  ) > "$log_file" 2>&1; then
    sed -n '1,240p' "$log_file" >&2
    fail "$entry_point updater unexpectedly failed for fixture: $project"
  fi
}

run_expected_failure() {
  local project="$1"
  local template="$2"
  local log_file="$3"

  if (
    cd "$project"
    PATH="$NO_NETWORK_BIN:$PATH" \
      TEMPLATE_REPO_URL="network-clone-must-not-run" \
      TEMPLATE_SOURCE_DIR="$template" \
      "$PYTHON" "$PYTHON_UPDATER"
  ) > "$log_file" 2>&1; then
    fail "Python updater unexpectedly accepted invalid fixture: $project"
  fi
  grep -F "ERROR" "$log_file" >/dev/null || fail "Failure was not prominent: $log_file"
}

assert_success_outcomes() {
  local project="$1"
  local template="$2"
  local expected="$3"
  local design_digest
  local design_archive
  local script_count

  assert_same "$expected/CLAUDE.md" "$project/CLAUDE.md" "preserved CLAUDE.md"
  assert_same "$expected/AGENTS.md" "$project/AGENTS.md" "preserved AGENTS.md"
  printf '%s\n' '{"threshold": "local"}' > "$expected/thresholds.json"
  assert_same \
    "$expected/thresholds.json" \
    "$project/.claude/backtest-thresholds.json" \
    "preserved thresholds"
  printf 'local design without newline' > "$expected/local-design.md"
  design_digest="$(sha256_file "$expected/local-design.md")"
  design_archive="$project/.claude/docs/DESIGN.local-preserved.sha256-${design_digest}.md"
  assert_same "$expected/local-design.md" "$design_archive" "content-addressed DESIGN archive"
  printf '%s\n' 'legacy archive unchanged' > "$expected/legacy-design.md"
  assert_same \
    "$expected/legacy-design.md" \
    "$project/.claude/docs/DESIGN.local-preserved.md" \
    "legacy DESIGN archive"
  assert_same \
    "$template/scripts/update.py" \
    "$project/scripts/update.py" \
    "self-updated Python updater"
  assert_same \
    "$template/scripts/validate_update_preservation.sh" \
    "$project/scripts/validate_update_preservation.sh" \
    "self-updated validator"
  assert_same \
    "$template/scripts/update.sh" \
    "$project/scripts/update.sh" \
    "self-updated shell wrapper"
  printf '%s\n' 'project owned' > "$expected/project-owned-decoy.sh"
  assert_same \
    "$expected/project-owned-decoy.sh" \
    "$project/scripts/project-owned-decoy.sh" \
    "project-owned scripts decoy"
  script_count="$(find "$project/scripts" -type f | wc -l | tr -d ' ')"
  [[ "$script_count" = "4" ]] || fail "Expected exactly four downstream scripts; found $script_count"
  [[ ! -e "$project/.claude/agents" ]] || fail "Legacy agents path survived"
  [[ ! -e "$project/.claude/routing-keywords.json" ]] || fail "Legacy routing path survived"
  [[ ! -e "$project/.gemini" ]] || fail "Legacy provider path survived"
}

mkdir -p "$NO_NETWORK_BIN"
cat > "$NO_NETWORK_BIN/git" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' 'ERROR: validation forbids the updater network clone path' >&2
exit 99
EOF
chmod +x "$NO_NETWORK_BIN/git"

EXPECTED="$FIXTURE_ROOT/expected"
make_expected_contracts "$EXPECTED"

PRIMARY_TEMPLATE="$FIXTURE_ROOT/primary-template"
PYTHON_PROJECT="$FIXTURE_ROOT/python-project"
SHELL_PROJECT="$FIXTURE_ROOT/shell-project"
make_template "$PRIMARY_TEMPLATE"
make_downstream "$PYTHON_PROJECT"
make_downstream "$SHELL_PROJECT"

run_update "python" "$PYTHON_PROJECT" "$PRIMARY_TEMPLATE" "$FIXTURE_ROOT/python-first.log"
assert_success_outcomes "$PYTHON_PROJECT" "$PRIMARY_TEMPLATE" "$EXPECTED"
run_update "python" "$PYTHON_PROJECT" "$PRIMARY_TEMPLATE" "$FIXTURE_ROOT/python-second.log"
assert_success_outcomes "$PYTHON_PROJECT" "$PRIMARY_TEMPLATE" "$EXPECTED"
ARCHIVE_COUNT="$(find "$PYTHON_PROJECT/.claude/docs" -type f \
  -name 'DESIGN.local-preserved.sha256-*.md' | wc -l | tr -d ' ')"
[[ "$ARCHIVE_COUNT" = "1" ]] || fail "Expected one deduplicated DESIGN archive"

run_update "shell" "$SHELL_PROJECT" "$PRIMARY_TEMPLATE" "$FIXTURE_ROOT/shell.log"
assert_success_outcomes "$SHELL_PROJECT" "$PRIMARY_TEMPLATE" "$EXPECTED"
assert_tree_same "$PYTHON_PROJECT" "$SHELL_PROJECT" "Python and shell entry-point outcomes"

EMPTY_TEMPLATE="$FIXTURE_ROOT/empty-template"
EMPTY_PROJECT="$FIXTURE_ROOT/empty-project"
make_template "$EMPTY_TEMPLATE"
make_downstream "$EMPTY_PROJECT"
{
  printf 'local\n@orchestra:template-boundary\n'
  printf '@orchestra:repo-boundary'
} > "$EMPTY_PROJECT/CLAUDE.md"
{
  printf 'local\r\n@codex:template-boundary\r\n'
  printf '@codex:repo-boundary'
} > "$EMPTY_PROJECT/AGENTS.md"
{
  printf '# Incoming CLAUDE\r\n'
  printf 'Prose containing @orchestra:template-boundary is not a marker.\r\n'
  printf '@orchestra:template-boundary\r\n'
  printf '@orchestra:repo-boundary\r\n'
} > "$EXPECTED/empty-CLAUDE.md"
{
  printf '# Incoming AGENTS\n'
  printf 'Prose containing @codex:repo-boundary is not a marker.\n'
  printf '@codex:template-boundary\n'
  printf '@codex:repo-boundary\n'
} > "$EXPECTED/empty-AGENTS.md"
run_update "python" "$EMPTY_PROJECT" "$EMPTY_TEMPLATE" "$FIXTURE_ROOT/empty.log"
assert_same "$EXPECTED/empty-CLAUDE.md" "$EMPTY_PROJECT/CLAUDE.md" "empty CLAUDE section"
assert_same "$EXPECTED/empty-AGENTS.md" "$EMPTY_PROJECT/AGENTS.md" "empty AGENTS section"

for location in local template; do
  for filename in CLAUDE.md AGENTS.md; do
    if [[ "$filename" = "CLAUDE.md" ]]; then
      START_MARKER="@orchestra:template-boundary"
      REPO_MARKER="@orchestra:repo-boundary"
    else
      START_MARKER="@codex:template-boundary"
      REPO_MARKER="@codex:repo-boundary"
    fi
    for variant in missing duplicate misordered; do
      CASE_NAME="$location-${filename%.*}-$variant"
      CASE_TEMPLATE="$FIXTURE_ROOT/$CASE_NAME-template"
      CASE_PROJECT="$FIXTURE_ROOT/$CASE_NAME-project"
      CASE_SNAPSHOT="$FIXTURE_ROOT/$CASE_NAME-snapshot"
      CASE_LOG="$FIXTURE_ROOT/$CASE_NAME.log"
      make_template "$CASE_TEMPLATE"
      make_downstream "$CASE_PROJECT"
      if [[ "$location" = "local" ]]; then
        INVALID_PATH="$CASE_PROJECT/$filename"
      else
        INVALID_PATH="$CASE_TEMPLATE/$filename"
      fi
      case "$variant" in
        missing)
          printf '# Missing marker\n%s\nProtected content.' \
            "$START_MARKER" > "$INVALID_PATH"
          EXPECTED_MARKER="$REPO_MARKER"
          ;;
        duplicate)
          printf '# Duplicate marker\n%s\n%s\n%s' \
            "$START_MARKER" "$START_MARKER" "$REPO_MARKER" > "$INVALID_PATH"
          EXPECTED_MARKER="$START_MARKER"
          ;;
        misordered)
          printf '# Misordered markers\n%s\nProtected content.\n%s' \
            "$REPO_MARKER" "$START_MARKER" > "$INVALID_PATH"
          EXPECTED_MARKER="$START_MARKER"
          ;;
      esac
      cp -R "$CASE_PROJECT" "$CASE_SNAPSHOT"
      run_expected_failure "$CASE_PROJECT" "$CASE_TEMPLATE" "$CASE_LOG"
      grep -F "$filename" "$CASE_LOG" >/dev/null || fail "$CASE_NAME omitted filename"
      grep -F "$EXPECTED_MARKER" "$CASE_LOG" >/dev/null || fail "$CASE_NAME omitted marker"
      if [[ "$variant" = "misordered" ]]; then
        grep -F "$REPO_MARKER" "$CASE_LOG" >/dev/null || fail "$CASE_NAME omitted marker"
      fi
      assert_tree_same "$CASE_SNAPSHOT" "$CASE_PROJECT" "$CASE_NAME preflight project"
    done
  done
done

COLLISION_TEMPLATE="$FIXTURE_ROOT/collision-template"
COLLISION_PROJECT="$FIXTURE_ROOT/collision-project"
COLLISION_SNAPSHOT="$FIXTURE_ROOT/collision-snapshot"
make_template "$COLLISION_TEMPLATE"
make_downstream "$COLLISION_PROJECT"
COLLISION_DIGEST="$(sha256_file "$COLLISION_PROJECT/.claude/docs/DESIGN.md")"
COLLISION_ARCHIVE="$COLLISION_PROJECT/.claude/docs/DESIGN.local-preserved.sha256-${COLLISION_DIGEST}.md"
printf '%s\n' 'wrong archive bytes' > "$COLLISION_ARCHIVE"
cp -R "$COLLISION_PROJECT" "$COLLISION_SNAPSHOT"
run_expected_failure \
  "$COLLISION_PROJECT" \
  "$COLLISION_TEMPLATE" \
  "$FIXTURE_ROOT/collision.log"
grep -F "digest collision or content mismatch" "$FIXTURE_ROOT/collision.log" >/dev/null || \
  fail "Archive collision diagnostic was missing"
assert_tree_same "$COLLISION_SNAPSHOT" "$COLLISION_PROJECT" "archive collision preflight project"

printf '%s\n' 'PASS: Python updater and shell wrapper preservation fixtures passed.'
