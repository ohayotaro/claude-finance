#!/usr/bin/env bash
#
# Validate the Python updater and its shell entry point using isolated offline
# fixtures. Expected output is one PASS line; failures print ERROR and exit.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
PYTHON_UPDATER="$SCRIPT_DIR/update.py"
SHELL_UPDATER="$SCRIPT_DIR/update.sh"
UPDATER_TEST="$SCRIPT_DIR/../tests/test_orchestration/test_update_script.py"
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
    "$root/scripts" \
    "$root/tests/test_orchestration"

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
  cp "$UPDATER_TEST" "$root/tests/test_orchestration/test_update_script.py"
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
    "$root/.codex/plans" \
    "$root/scripts" \
    "$root/tests/test_orchestration"

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
  printf '%s\n' 'existing content-addressed archive unchanged' > \
    "$root/.claude/docs/DESIGN.local-preserved.sha256-existing.md"
  printf '%s\n' 'preserved task' > "$root/.claude/tasks/task-1/brief.md"
  printf '%s\n' 'preserved log' > "$root/.claude/logs/preserved.log"
  printf '%s\n' 'local codex config' > "$root/.codex/config.toml"
  printf 'project codex plan\r\nwithout final newline' > "$root/.codex/plans/decoy.md"
  printf '%s\n' 'stale updater' > "$root/scripts/update.py"
  printf '%s\n' 'stale updater' > "$root/scripts/validate_update_preservation.sh"
  printf '%s\n' 'stale updater' > "$root/scripts/update.sh"
  printf '%s\n' 'project owned' > "$root/scripts/project-owned-decoy.sh"
  printf '%s\n' 'stale updater test' > "$root/tests/test_orchestration/test_update_script.py"
  printf '%s\n' 'project owned test' > "$root/tests/project-owned-decoy.py"

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
  local script_count

  assert_same "$expected/CLAUDE.md" "$project/CLAUDE.md" "preserved CLAUDE.md"
  assert_same "$expected/AGENTS.md" "$project/AGENTS.md" "preserved AGENTS.md"
  printf '%s\n' '{"threshold": "local"}' > "$expected/thresholds.json"
  assert_same \
    "$expected/thresholds.json" \
    "$project/.claude/backtest-thresholds.json" \
    "preserved thresholds"
  printf 'local design without newline' > "$expected/local-design.md"
  assert_same \
    "$expected/local-design.md" \
    "$project/.claude/docs/DESIGN.md" \
    "preserved local DESIGN.md"
  printf '%s\n' 'legacy archive unchanged' > "$expected/legacy-design.md"
  assert_same \
    "$expected/legacy-design.md" \
    "$project/.claude/docs/DESIGN.local-preserved.md" \
    "legacy DESIGN archive"
  printf '%s\n' 'existing content-addressed archive unchanged' > \
    "$expected/content-addressed-design.md"
  assert_same \
    "$expected/content-addressed-design.md" \
    "$project/.claude/docs/DESIGN.local-preserved.sha256-existing.md" \
    "existing content-addressed DESIGN archive"
  assert_same \
    "$template/.codex/config.toml" \
    "$project/.codex/config.toml" \
    "template-managed Codex config"
  printf 'project codex plan\r\nwithout final newline' > "$expected/codex-plan.md"
  assert_same \
    "$expected/codex-plan.md" \
    "$project/.codex/plans/decoy.md" \
    "project-owned Codex plan"
  assert_same \
    "$template/scripts/update.py" \
    "$project/scripts/update.py" \
    "self-updated Python updater"
  assert_same \
    "$template/scripts/validate_update_preservation.sh" \
    "$project/scripts/validate_update_preservation.sh" \
    "self-updated validator"
  assert_same \
    "$template/tests/test_orchestration/test_update_script.py" \
    "$project/tests/test_orchestration/test_update_script.py" \
    "self-updated updater test"
  assert_same \
    "$template/scripts/update.sh" \
    "$project/scripts/update.sh" \
    "self-updated shell wrapper"
  printf '%s\n' 'project owned' > "$expected/project-owned-decoy.sh"
  assert_same \
    "$expected/project-owned-decoy.sh" \
    "$project/scripts/project-owned-decoy.sh" \
    "project-owned scripts decoy"
  printf '%s\n' 'project owned test' > "$expected/project-owned-test.py"
  assert_same \
    "$expected/project-owned-test.py" \
    "$project/tests/project-owned-decoy.py" \
    "project-owned tests decoy"
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

run_update "shell" "$SHELL_PROJECT" "$PRIMARY_TEMPLATE" "$FIXTURE_ROOT/shell.log"
assert_success_outcomes "$SHELL_PROJECT" "$PRIMARY_TEMPLATE" "$EXPECTED"
assert_tree_same "$PYTHON_PROJECT" "$SHELL_PROJECT" "Python and shell entry-point outcomes"

ABSENT_DESIGN_TEMPLATE="$FIXTURE_ROOT/absent-design-template"
ABSENT_DESIGN_PYTHON_PROJECT="$FIXTURE_ROOT/absent-design-python-project"
ABSENT_DESIGN_SHELL_PROJECT="$FIXTURE_ROOT/absent-design-shell-project"
make_template "$ABSENT_DESIGN_TEMPLATE"
make_downstream "$ABSENT_DESIGN_PYTHON_PROJECT"
make_downstream "$ABSENT_DESIGN_SHELL_PROJECT"
rm "$ABSENT_DESIGN_PYTHON_PROJECT/.claude/docs/DESIGN.md"
rm "$ABSENT_DESIGN_SHELL_PROJECT/.claude/docs/DESIGN.md"
cp "$ABSENT_DESIGN_TEMPLATE/.claude/docs/DESIGN.md" "$EXPECTED/initial-design.md"
run_update \
  "python" \
  "$ABSENT_DESIGN_PYTHON_PROJECT" \
  "$ABSENT_DESIGN_TEMPLATE" \
  "$FIXTURE_ROOT/absent-design-python-first.log"
run_update \
  "shell" \
  "$ABSENT_DESIGN_SHELL_PROJECT" \
  "$ABSENT_DESIGN_TEMPLATE" \
  "$FIXTURE_ROOT/absent-design-shell-first.log"
assert_same \
  "$EXPECTED/initial-design.md" \
  "$ABSENT_DESIGN_PYTHON_PROJECT/.claude/docs/DESIGN.md" \
  "initial Python DESIGN scaffold"
assert_same \
  "$EXPECTED/initial-design.md" \
  "$ABSENT_DESIGN_SHELL_PROJECT/.claude/docs/DESIGN.md" \
  "initial shell DESIGN scaffold"
printf '%s\n' 'changed incoming design' > "$ABSENT_DESIGN_TEMPLATE/.claude/docs/DESIGN.md"
run_update \
  "python" \
  "$ABSENT_DESIGN_PYTHON_PROJECT" \
  "$ABSENT_DESIGN_TEMPLATE" \
  "$FIXTURE_ROOT/absent-design-python-second.log"
run_update \
  "shell" \
  "$ABSENT_DESIGN_SHELL_PROJECT" \
  "$ABSENT_DESIGN_TEMPLATE" \
  "$FIXTURE_ROOT/absent-design-shell-second.log"
assert_same \
  "$EXPECTED/initial-design.md" \
  "$ABSENT_DESIGN_PYTHON_PROJECT/.claude/docs/DESIGN.md" \
  "preserved Python DESIGN scaffold"
assert_same \
  "$EXPECTED/initial-design.md" \
  "$ABSENT_DESIGN_SHELL_PROJECT/.claude/docs/DESIGN.md" \
  "preserved shell DESIGN scaffold"

NO_CODEX_TEMPLATE="$FIXTURE_ROOT/no-codex-template"
NO_CODEX_PYTHON_PROJECT="$FIXTURE_ROOT/no-codex-python-project"
NO_CODEX_SHELL_PROJECT="$FIXTURE_ROOT/no-codex-shell-project"
make_template "$NO_CODEX_TEMPLATE"
rm -rf "$NO_CODEX_TEMPLATE/.codex"
make_downstream "$NO_CODEX_PYTHON_PROJECT"
make_downstream "$NO_CODEX_SHELL_PROJECT"
cp -R "$NO_CODEX_PYTHON_PROJECT/.codex" "$FIXTURE_ROOT/no-codex-python-snapshot"
cp -R "$NO_CODEX_SHELL_PROJECT/.codex" "$FIXTURE_ROOT/no-codex-shell-snapshot"
run_update \
  "python" \
  "$NO_CODEX_PYTHON_PROJECT" \
  "$NO_CODEX_TEMPLATE" \
  "$FIXTURE_ROOT/no-codex-python.log"
run_update \
  "shell" \
  "$NO_CODEX_SHELL_PROJECT" \
  "$NO_CODEX_TEMPLATE" \
  "$FIXTURE_ROOT/no-codex-shell.log"
assert_tree_same \
  "$FIXTURE_ROOT/no-codex-python-snapshot" \
  "$NO_CODEX_PYTHON_PROJECT/.codex" \
  "downstream-only Python Codex tree"
assert_tree_same \
  "$FIXTURE_ROOT/no-codex-shell-snapshot" \
  "$NO_CODEX_SHELL_PROJECT/.codex" \
  "downstream-only shell Codex tree"

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

printf '%s\n' 'PASS: Python updater and shell wrapper preservation fixtures passed.'
