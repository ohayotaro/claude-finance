# 実装計画

計画のみを作成しました。リポジトリは変更しておらず、現在の未追跡変更はタスク brief ディレクトリだけです。ネットワークアクセス、updater 実行、テスト実行は行っていません。

## 推奨設計と理由

[scripts/update.py](/Users/ohayotaro/claude-finance/scripts/update.py:455) の `.codex` 処理だけを、ディレクトリ全置換から staged file overlay に変更します。

- テンプレートの `.codex` が存在しなければ、空の更新リストを返し、downstream の `.codex` には一切触れません。
- 存在する場合はツリーを安定した順序で再帰走査し、各エントリを mutation 前に検証します。
  - ディレクトリは symlink でない安全なディレクトリであること。
  - ファイルは symlink でない regular file であること。
  - その他の特殊ファイルは fail-closed。
  - downstream の対応先は、既存なら安全な regular file であること。
  - 対応先までの既存親パスは、安全な非 symlink ディレクトリであること。
- 検証済みファイルを `work_dir/staged/.codex/` 以下へ stage し、typed な `(staged_source, downstream_destination)` の tuple として `UpdatePlan` に保持します。
- 静的な `RECOVERY_PATHS` から `.codex` 全体を外し、更新対象となる `.codex` ファイルだけを recovery 対象へ動的に追加します。
  - 既存ファイルは mutation 前にコピー。
  - 未存在ファイルは既存の `originally-absent.txt` に記録。
  - `.codex/plans/` など非管理ファイルは変更も recovery コピーも行いません。
- mutation フェーズでは `_remove_path(.codex)` と `_copy_tree()` を廃止し、staged file ごとに既存の `_replace_file()` を呼びます。必要な親ディレクトリだけが作成されます。
- `.claude/hooks|rules|skills|scripts` の全置換処理、contract composition、DESIGN archive、self-update の順序と意味は変更しません。
- module docstring に mixed-ownership 契約を明記します。
- README は更新時の `.codex` が file-level overlay であり、template にない downstream content と template `.codex` 不在時のツリー全体が保持されることを明記します。

この設計は、将来テンプレートに `.codex/config.toml` 以外のファイルが増えても whitelist 更新を不要にしつつ、テンプレートが実際に所有するファイルだけを置換できます。

## 代替案

- `shutil.copytree(..., dirs_exist_ok=True)` による merge:
  実装は短いものの、個々の source/target と親パスに対する fail-closed 検証、staging、対象別 recovery を明示できないため採用しません。
- `.codex/config.toml` だけを固定 whitelist にする:
  現状は足りますが、「テンプレート `.codex` 内のすべてのファイル」という要件を満たさず、将来の template file を取りこぼすため採用しません。
- `.codex` 全体の recovery コピーを維持する:
  機能上は可能ですが、変更しない project-owned plans まで一時領域へ複製し、容量や機密性の面で不要です。管理対象ファイルだけの recovery を推奨します。
- 過去の template-managed file を manifest で追跡して削除する:
  現在は ownership metadata がなく、project-owned file を誤削除する可能性があります。また、今回の「他の `.codex` path は削除しない」という契約に反します。
- destination がディレクトリや symlink の場合に自動削除して置換する:
  silent data loss や template root 外への書き込みにつながるため、mutation 前にエラーとします。

## 影響ファイルとコンポーネント

- [scripts/update.py](/Users/ohayotaro/claude-finance/scripts/update.py:58)
  - `UpdatePlan`
  - `.codex` 再帰 preflight/staging helper
  - dynamic recovery target
  - `_apply_update()` の `.codex` file overlay
  - module safety contract
- [scripts/validate_update_preservation.sh](/Users/ohayotaro/claude-finance/scripts/validate_update_preservation.sh:97)
  - downstream `.codex/plans/decoy.md`
  - template config replacement assertion
  - template `.codex` 不在 fixture
- [tests/test_orchestration/test_update_script.py](/Users/ohayotaro/claude-finance/tests/test_orchestration/test_update_script.py:110)
  - decoy fixtureと byte assertions
  - missing-template `.codex` regression test
  - unsafe `.codex` path preflight tests
  - recovery assertion
- [README.md](/Users/ohayotaro/claude-finance/README.md:184)
  - mixed-ownership と preservation semantics の説明

変更対象外:

- `scripts/update.sh`
- `.claude/hooks|rules|skills|scripts` の置換契約
- `src/`、runner、registry、ignore rules
- downstream repository、Git index/history、依存関係

## 実装順序

1. T2 計画承認後、worktree を再確認し、未追跡の task brief を保護する。
2. `.codex` file mapping を保持する typed field を `UpdatePlan` に追加する。
3. template `.codex` の再帰検証、downstream 親/target 検証、staging を行う helper を追加する。
4. `_prepare_update()` で helper を mutation 前に実行し、全 source/target が安全であることを確定する。
5. `.codex` 全体を静的 recovery 対象から外し、管理対象 destination を `_create_recovery()` に追加する。
6. `_apply_update()` の `.codex` 削除と tree copy を staged file replacement loop に置換する。
7. pytest fixture、missing-template test、fail-closed safety test、recovery test を更新する。
8. Bash validator に同等の decoy/config/missing-template assertions を追加する。
9. module docstring と README を更新し、変更範囲をレビューする。
10. fixture-only、offline の検証を順番に実行する。

## テスト・検証計画

Fixture 検証:

- `.codex/plans/decoy.md` に改行形式と末尾改行を含む固定 byte sequence を置き、1回目と再実行後の双方で完全一致を確認。
- `.codex/config.toml` が template bytes と完全一致することを確認。
- template `.codex` を除いた独立 fixture で、更新前後の downstream `.codex` tree manifest を完全比較。
- template `.codex` 内の symlink/特殊 path、または downstream target/親ディレクトリ衝突が mutation 前に拒否され、project tree が不変であることを確認。
- late failure test で、元の `.codex/config.toml` が recovery に存在することを確認。
- Python entry point と shell wrapper の既存 parity、marker rejection、Zone B/C、AGENTS、DESIGN、self-update tests を維持。

実行コマンド:

```bash
bash scripts/validate_update_preservation.sh

uv run --extra dev pytest tests/test_orchestration/test_update_script.py
uv run --extra dev pytest -m "not integration and not slow"

uv run --extra dev ruff check src/ tests/ .claude/hooks/ .claude/scripts/ scripts/update.py
uv run --extra dev mypy src/ .claude/scripts/ scripts/update.py

for file in scripts/validate_update_preservation.sh scripts/update.sh; do
  bash -n "$file"
  shellcheck "$file"
done

git diff --check
```

追加の静的確認として、変更ファイルの ASCII-only 検査、README/docstring の `.codex` ownership 文言検索、変更範囲が許可された4ファイルに限定されていることを確認します。

すべての updater 実行は `TEMPLATE_SOURCE_DIR` を指定した一時 fixture 内でのみ行います。repository root や実 downstream repository では実行しません。`uv` が download や network access を試行した場合は直ちに停止し、`BLOCKED` と報告します。

## リスクとブロッカー

- 更新は複数ファイルにまたがり完全には atomic ではありません。既存の manual recovery 契約は残ります。
- preflight 後に別プロセスが destination を変更する TOCTOU は完全には排除できません。並行 updater 実行は引き続き unsupported です。
- 新規 managed file の親ディレクトリは late failure 後に残る可能性があります。元ファイルの recovery と absent 記録は残りますが、自動 rollback は非目標です。
- destination に project-owned directory があり、template が同じ path を file として所有する場合は、安全のため更新全体が fail-closed になります。
- Windows runtime 検証は利用できません。standard-library、`pathlib`、非 POSIX API 不使用による静的互換性確認が残余リスクです。
- 財務、取引、risk control、credential に対する影響はありません。
- 現時点の技術的ブロッカーはありません。実装開始には T2 承認が必要です。

## Acceptance Criteria 対応

| AC | 設計・検証対応 |
|---|---|
| AC1 | 両 fixture に `.codex/plans/decoy.md` を追加し、更新前の固定 bytes と更新後を比較。同時に `.codex/config.toml` が template bytes に置換されたことを確認。再実行でも検証。 |
| AC2 | template `.codex` を欠く fixture を作り、downstream `.codex` の全 entry/type/bytes manifest が更新前後で同一であることを pytest と validator で確認。 |
| AC3 | `.claude`、CLAUDE/AGENTS sections、DESIGN archive、self-update、marker fail-closed の既存テストを変更せず維持し、validator 全体と updater suite を実行。 |
| AC4 | 指定の fast pytest、ruff、mypy を実行。変更 shell validator と関連 wrapper に `bash -n` と shellcheck を実行。結果と validator の PASS output を実装報告に記録。 |
| AC5 | module docstring と README の updater section に mixed-ownership、file-level replacement、missing-template no-op を明記。全文検索とレビューで wholesale `.codex` replacement の記述がないことを確認。 |