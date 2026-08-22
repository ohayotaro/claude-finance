#!/usr/bin/env bash
#
# Validate scripts/update.sh preservation behavior with isolated downstream and
# template fixtures. Expected output is one PASS line; any failed assertion
# prints an ERROR line and exits non-zero. TEMPLATE_SOURCE_DIR is always set,
# and a git shim fails if the updater attempts its network clone path.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
UPDATER="$SCRIPT_DIR/update.sh"
FIXTURE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/validate-update-preservation.XXXXXX")"
NO_NETWORK_BIN="$FIXTURE_ROOT/no-network-bin"

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

make_template() {
  local root="$1"

  mkdir -p \
    "$root/.claude/hooks" \
    "$root/.claude/rules" \
    "$root/.claude/skills" \
    "$root/.claude/scripts" \
    "$root/.claude/docs" \
    "$root/.codex"

  cat > "$root/CLAUDE.md" <<'EOF'
# Incoming CLAUDE contract

Prose containing @orchestra:template-boundary is not a marker line.
@orchestra:template-boundary
Incoming Zone B must be replaced.
@orchestra:repo-boundary
Incoming Zone C must be replaced.
EOF

  cat > "$root/AGENTS.md" <<'EOF'
# Incoming AGENTS contract

Prose containing @codex:repo-boundary is not a marker line.
@codex:template-boundary
Incoming project section must be replaced.
@codex:repo-boundary
Incoming post-boundary section must be replaced.
EOF

  printf '%s\n' 'incoming hook' > "$root/.claude/hooks/example.py"
  printf '%s\n' 'incoming rule' > "$root/.claude/rules/example.md"
  printf '%s\n' 'incoming skill' > "$root/.claude/skills/example.md"
  printf '%s\n' 'incoming script' > "$root/.claude/scripts/example.py"
  printf '%s\n' '{"incoming": true}' > "$root/.claude/settings.json"
  printf '%s\n' '{"threshold": "incoming"}' > "$root/.claude/backtest-thresholds.json"
  printf '%s\n' '# Incoming task contract' > "$root/.claude/docs/CODEX_TASK_CONTRACT.md"
  printf '%s\n' '# Incoming design' 'Template design revision.' > "$root/.claude/docs/DESIGN.md"
  printf '%s\n' 'incoming codex config' > "$root/.codex/config.toml"
}

make_downstream() {
  local root="$1"

  mkdir -p \
    "$root/.claude/hooks" \
    "$root/.claude/rules" \
    "$root/.claude/skills" \
    "$root/.claude/scripts" \
    "$root/.claude/docs" \
    "$root/.codex"

  cat > "$root/CLAUDE.md" <<'EOF'
# Local CLAUDE contract

@orchestra:template-boundary
Local Zone B line one.
Embedded @orchestra:repo-boundary text remains Zone B content.
Local Zone B line three.
@orchestra:repo-boundary
Local Zone C line one.
Embedded @orchestra:template-boundary text remains Zone C content.
Local Zone C final line.
EOF

  cat > "$root/AGENTS.md" <<'EOF'
# Local AGENTS contract

@codex:template-boundary
Local project section line one.
Embedded @codex:repo-boundary text remains project content.
Local project section final line.
@codex:repo-boundary
Local post-boundary line one.
Embedded @codex:template-boundary text remains post-boundary content.
Local post-boundary final line.
EOF

  printf '%s\n' 'local hook' > "$root/.claude/hooks/local.py"
  printf '%s\n' 'local rule' > "$root/.claude/rules/local.md"
  printf '%s\n' 'local skill' > "$root/.claude/skills/local.md"
  printf '%s\n' 'local script' > "$root/.claude/scripts/local.py"
  printf '%s\n' '{"local": true}' > "$root/.claude/settings.json"
  printf '%s\n' '{"threshold": "local-preserved"}' > "$root/.claude/backtest-thresholds.json"
  printf '%s\n' '# Local task contract' > "$root/.claude/docs/CODEX_TASK_CONTRACT.md"
  printf '%s\n' '# Local design' 'Local ADR must remain recoverable.' > "$root/.claude/docs/DESIGN.md"
  printf '%s\n' 'legacy archive must remain unchanged' > "$root/.claude/docs/DESIGN.local-preserved.md"
  printf '%s\n' 'local codex config' > "$root/.codex/config.toml"
}

run_update() {
  local project="$1"
  local template="$2"
  local log_file="$3"

  if ! (
    cd "$project"
    PATH="$NO_NETWORK_BIN:$PATH" \
      TEMPLATE_REPO_URL="network-clone-must-not-run" \
      TEMPLATE_SOURCE_DIR="$template" \
      "$UPDATER"
  ) > "$log_file" 2>&1; then
    sed -n '1,240p' "$log_file" >&2
    fail "Updater unexpectedly failed for fixture: $project"
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
      "$UPDATER"
  ) > "$log_file" 2>&1; then
    fail "Updater unexpectedly accepted invalid markers: $project"
  fi
  grep -F "ERROR" "$log_file" >/dev/null || fail "Failure output was not prominent: $log_file"
}

assert_preflight_failure_unchanged() {
  local project="$1"
  local template="$2"
  local case_name="$3"
  local snapshot="$FIXTURE_ROOT/snapshot-$case_name"
  local log_file="$FIXTURE_ROOT/$case_name.log"

  mkdir -p "$snapshot/.claude/docs"
  cp "$project/CLAUDE.md" "$snapshot/CLAUDE.md"
  cp "$project/AGENTS.md" "$snapshot/AGENTS.md"
  cp "$project/.claude/backtest-thresholds.json" "$snapshot/.claude/backtest-thresholds.json"
  cp "$project/.claude/docs/DESIGN.md" "$snapshot/.claude/docs/DESIGN.md"

  run_expected_failure "$project" "$template" "$log_file"
  assert_same "$snapshot/CLAUDE.md" "$project/CLAUDE.md" "$case_name CLAUDE.md"
  assert_same "$snapshot/AGENTS.md" "$project/AGENTS.md" "$case_name AGENTS.md"
  assert_same \
    "$snapshot/.claude/backtest-thresholds.json" \
    "$project/.claude/backtest-thresholds.json" \
    "$case_name thresholds"
  assert_same \
    "$snapshot/.claude/docs/DESIGN.md" \
    "$project/.claude/docs/DESIGN.md" \
    "$case_name DESIGN.md"
}

mkdir -p "$NO_NETWORK_BIN"
cat > "$NO_NETWORK_BIN/git" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' 'ERROR: validation forbids the updater network clone path' >&2
exit 99
EOF
chmod +x "$NO_NETWORK_BIN/git"

PRIMARY_TEMPLATE="$FIXTURE_ROOT/primary-template"
PRIMARY_PROJECT="$FIXTURE_ROOT/primary-project"
EXPECTED="$FIXTURE_ROOT/expected"
mkdir -p "$EXPECTED/.claude/docs"
make_template "$PRIMARY_TEMPLATE"
make_downstream "$PRIMARY_PROJECT"

cat > "$EXPECTED/CLAUDE.md" <<'EOF'
# Incoming CLAUDE contract

Prose containing @orchestra:template-boundary is not a marker line.
@orchestra:template-boundary
Local Zone B line one.
Embedded @orchestra:repo-boundary text remains Zone B content.
Local Zone B line three.
@orchestra:repo-boundary
Local Zone C line one.
Embedded @orchestra:template-boundary text remains Zone C content.
Local Zone C final line.
EOF

cat > "$EXPECTED/AGENTS.md" <<'EOF'
# Incoming AGENTS contract

Prose containing @codex:repo-boundary is not a marker line.
@codex:template-boundary
Local project section line one.
Embedded @codex:repo-boundary text remains project content.
Local project section final line.
@codex:repo-boundary
Local post-boundary line one.
Embedded @codex:template-boundary text remains post-boundary content.
Local post-boundary final line.
EOF

cp "$PRIMARY_PROJECT/.claude/backtest-thresholds.json" "$EXPECTED/backtest-thresholds.json"
cp "$PRIMARY_PROJECT/.claude/docs/DESIGN.md" "$EXPECTED/local-DESIGN.md"
cp "$PRIMARY_PROJECT/.claude/docs/DESIGN.local-preserved.md" "$EXPECTED/legacy-DESIGN.md"

for old_backup in \
  .zone-b.backup.md \
  .agents-project.backup.md \
  .backtest-thresholds.backup.json \
  .design-local.backup.md
do
  printf '%s\n' "reserved-name sentinel: $old_backup" > "$PRIMARY_PROJECT/$old_backup"
  cp "$PRIMARY_PROJECT/$old_backup" "$EXPECTED/$old_backup"
done

run_update "$PRIMARY_PROJECT" "$PRIMARY_TEMPLATE" "$FIXTURE_ROOT/primary-first.log"
assert_same "$EXPECTED/CLAUDE.md" "$PRIMARY_PROJECT/CLAUDE.md" "preserved CLAUDE sections"
assert_same "$EXPECTED/AGENTS.md" "$PRIMARY_PROJECT/AGENTS.md" "preserved AGENTS sections"
assert_same \
  "$EXPECTED/backtest-thresholds.json" \
  "$PRIMARY_PROJECT/.claude/backtest-thresholds.json" \
  "preserved backtest thresholds"

DESIGN_DIGEST="$(sha256_file "$EXPECTED/local-DESIGN.md")"
DESIGN_ARCHIVE="$PRIMARY_PROJECT/.claude/docs/DESIGN.local-preserved.sha256-${DESIGN_DIGEST}.md"
assert_same "$EXPECTED/local-DESIGN.md" "$DESIGN_ARCHIVE" "content-addressed DESIGN archive"
assert_same \
  "$EXPECTED/legacy-DESIGN.md" \
  "$PRIMARY_PROJECT/.claude/docs/DESIGN.local-preserved.md" \
  "legacy DESIGN archive"

run_update "$PRIMARY_PROJECT" "$PRIMARY_TEMPLATE" "$FIXTURE_ROOT/primary-second.log"
assert_same "$EXPECTED/CLAUDE.md" "$PRIMARY_PROJECT/CLAUDE.md" "second-run CLAUDE sections"
assert_same "$EXPECTED/AGENTS.md" "$PRIMARY_PROJECT/AGENTS.md" "second-run AGENTS sections"
assert_same "$EXPECTED/local-DESIGN.md" "$DESIGN_ARCHIVE" "second-run DESIGN archive"
assert_same \
  "$EXPECTED/legacy-DESIGN.md" \
  "$PRIMARY_PROJECT/.claude/docs/DESIGN.local-preserved.md" \
  "second-run legacy DESIGN archive"

ARCHIVE_COUNT="$(find "$PRIMARY_PROJECT/.claude/docs" -type f -name 'DESIGN.local-preserved.sha256-*.md' | wc -l | tr -d ' ')"
[[ "$ARCHIVE_COUNT" = "1" ]] || fail "Expected one deduplicated DESIGN archive; found $ARCHIVE_COUNT"
for old_backup in \
  .zone-b.backup.md \
  .agents-project.backup.md \
  .backtest-thresholds.backup.json \
  .design-local.backup.md
do
  assert_same "$EXPECTED/$old_backup" "$PRIMARY_PROJECT/$old_backup" "reserved backup name $old_backup"
done

EMPTY_TEMPLATE="$FIXTURE_ROOT/empty-template"
EMPTY_PROJECT="$FIXTURE_ROOT/empty-project"
make_template "$EMPTY_TEMPLATE"
make_downstream "$EMPTY_PROJECT"
cat > "$EMPTY_PROJECT/CLAUDE.md" <<'EOF'
# Local empty CLAUDE sections
@orchestra:template-boundary
@orchestra:repo-boundary
EOF
cat > "$EMPTY_PROJECT/AGENTS.md" <<'EOF'
# Local empty AGENTS sections
@codex:template-boundary
@codex:repo-boundary
EOF
cat > "$EXPECTED/empty-CLAUDE.md" <<'EOF'
# Incoming CLAUDE contract

Prose containing @orchestra:template-boundary is not a marker line.
@orchestra:template-boundary
@orchestra:repo-boundary
EOF
cat > "$EXPECTED/empty-AGENTS.md" <<'EOF'
# Incoming AGENTS contract

Prose containing @codex:repo-boundary is not a marker line.
@codex:template-boundary
@codex:repo-boundary
EOF
run_update "$EMPTY_PROJECT" "$EMPTY_TEMPLATE" "$FIXTURE_ROOT/empty.log"
assert_same "$EXPECTED/empty-CLAUDE.md" "$EMPTY_PROJECT/CLAUDE.md" "empty CLAUDE sections"
assert_same "$EXPECTED/empty-AGENTS.md" "$EMPTY_PROJECT/AGENTS.md" "empty AGENTS sections"

CASE_PROJECT="$FIXTURE_ROOT/missing-local-claude"
CASE_TEMPLATE="$FIXTURE_ROOT/missing-local-claude-template"
make_downstream "$CASE_PROJECT"
make_template "$CASE_TEMPLATE"
cat > "$CASE_PROJECT/CLAUDE.md" <<'EOF'
# Missing local CLAUDE repository marker
@orchestra:template-boundary
Protected local content.
EOF
assert_preflight_failure_unchanged "$CASE_PROJECT" "$CASE_TEMPLATE" "missing-local-claude"

CASE_PROJECT="$FIXTURE_ROOT/missing-local-agents"
CASE_TEMPLATE="$FIXTURE_ROOT/missing-local-agents-template"
make_downstream "$CASE_PROJECT"
make_template "$CASE_TEMPLATE"
cat > "$CASE_PROJECT/AGENTS.md" <<'EOF'
# Missing local AGENTS start marker
Protected local content.
@codex:repo-boundary
Protected local tail.
EOF
assert_preflight_failure_unchanged "$CASE_PROJECT" "$CASE_TEMPLATE" "missing-local-agents"

CASE_PROJECT="$FIXTURE_ROOT/duplicate-template-claude"
CASE_TEMPLATE="$FIXTURE_ROOT/duplicate-template-claude-template"
make_downstream "$CASE_PROJECT"
make_template "$CASE_TEMPLATE"
cat > "$CASE_TEMPLATE/CLAUDE.md" <<'EOF'
# Duplicate incoming CLAUDE start marker
@orchestra:template-boundary
Incoming content.
@orchestra:template-boundary
More incoming content.
@orchestra:repo-boundary
Incoming tail.
EOF
assert_preflight_failure_unchanged "$CASE_PROJECT" "$CASE_TEMPLATE" "duplicate-template-claude"

CASE_PROJECT="$FIXTURE_ROOT/misordered-template-agents"
CASE_TEMPLATE="$FIXTURE_ROOT/misordered-template-agents-template"
make_downstream "$CASE_PROJECT"
make_template "$CASE_TEMPLATE"
cat > "$CASE_TEMPLATE/AGENTS.md" <<'EOF'
# Misordered incoming AGENTS markers
@codex:repo-boundary
Incoming content.
@codex:template-boundary
EOF
assert_preflight_failure_unchanged "$CASE_PROJECT" "$CASE_TEMPLATE" "misordered-template-agents"

printf '%s\n' 'PASS: update preservation fixtures passed.'
