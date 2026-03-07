# P9-CR-D-Docs-01: disclosure README/Docs更新 クロスレビュー

**レビュアー**: 足軽7号
**対象タスク**: D-Docs-01（足軽8担当・commit 2f5cf24）
**レビュー日**: 2026-03-09
**判定**: ⚠️ 条件付き承認（必須修正1件）

---

## 対象ファイル

| ファイル | commit | 状態 |
|--------|--------|------|
| `README.md` | 2f5cf24 | 更新 |
| `docs/CHANGELOG.md` | 2f5cf24 | 新規作成 |
| `laws/README.md` | 2f5cf24 | 新規作成 |

---

## CR-1: README.md の正確性 ✅

### SSBJ対応記述
- `ssbj_2025.yaml` 25件: L118「sb-2025-001 〜 sb-2025-025」✅
  → 実際のYAML grep件数: **25件**（`grep -c '^\s*- id:' laws/ssbj_2025.yaml`）
- CL-026〜CL-035: README.mdには記述なし（api/data/checklist_data.json のUIエントリ番号）
  → READMEへの記述は不要。問題なし ✅
- 2027年3月期強制適用: README.mdには記述なし（ssbj_2025.yaml コメント内に記載）
  → 欠落ではなく省略と判断。問題なし ✅

### 招集通知対応記述
- `shareholder_notice_2025.yaml` 16件: L119 ✅
  → 実際のYAML grep件数: **16件**（`grep -c '^\s*- id:' laws/shareholder_notice_2025.yaml`）
- `DocTypeCode`: FastAPI例「`"doc_type_code": "shoshu"`」L106 ✅
- `doc_type="shoshu"`: L97-98に記載 ✅

### LAW_YAML_DIR修正記述
- 環境変数例: L76-77「`export LAW_YAML_DIR=/path/to/custom/laws`」✅
- `laws/`配下自動読み込み: L112-122 ✅
- L122「再起動不要」: m2_law_agent.py の実装確認 → `get_law_entries()` 呼び出し時に毎回 `_load_all_from_dir(LAW_YAML_DIR)` を実行 → **「再起動不要」は正しい** ✅

### テスト件数
- モジュール別合計: 47+26+23+48+46+13+15+15+12 = **245件**
- E2E統合テスト: **48件**（test_e2e_pipeline/batch/smoke/phase2）
- 合計: 245+48 = **293件** → L63「総テスト数: 293件」✅

---

## CR-2: CHANGELOG.md の内容確認 ⚠️（必須修正1件）

### commit ID確認（git log照合）

| エントリ | CHANGELOG記載 commit | git log実際 | 判定 |
|---------|-------------------|------------|------|
| D-SSBJ-01 | 60608de | `60608de feat(D-SSBJ-01): SSBJ対応 4ファイル追加・修正` | ✅ |
| D-Shoshu-01 | 62ae09c〜f4ca3b0 | 62ae09c(YAML追加)〜f4ca3b0(P9-CR完了) | ✅ |
| D-LAW-DIR-fix | 78fbfb8 | `78fbfb8 fix(D-LAW-DIR-fix): m2 LAW_YAML_DIR を laws/ に修正` | ✅ |
| D-Zenn-03-fix | 0dde91a | `0dde91a fix(D-Zenn-03-fix): P9-CR-D-Zenn-03必須修正2件対応` | ✅ |

### 🔴 M-1（必須修正）: D-SSBJ-01セクションのhuman_capital_2024.yaml帰属誤り

**現状記述**（CHANGELOG.md L33-34）:
```
- `laws/human_capital_2024.yaml` 追加: 人的資本（hc-2024-xxx × 4）+ SSBJ 2024 年（sb-2024-xxx × 4）= 8件
```

**事実**:
`git show 60608de --stat` を確認したところ、60608deのcommitには以下6ファイルしか含まれていない:
- `api/data/checklist_data.json`（CL-026〜CL-035追加）
- `laws/ssbj_2025.yaml`（新規作成）
- `scripts/m3_gap_analysis_agent.py`
- `scripts/m4_proposal_agent.py`
- `scripts/test_m3_gap_analysis.py`
- `scripts/test_m4_proposal.py`

**human_capital_2024.yaml は 60608de には含まれていない**。
実際のgit追跡: `git log --follow laws/human_capital_2024.yaml` → `bfc4a9f chore(P14): 全ファイルgit追跡化`（D-SSBJ-01より前のコミット）。

**必須修正**: CHANGELOG.md D-SSBJ-01セクションから `laws/human_capital_2024.yaml` 追加の記述を削除、または正確な帰属（P14追跡化コミット）に修正せよ。

### D-Shoshu-01の変更内容
- `SHOSHU_SECTION_KEYWORDS` 12項目 ✅
- `SHOSHU_HEADING_PATTERNS` 8パターン ✅
- `DocTypeCode(str, Enum)` 追加 ✅
- `TestShoshuDocType` 15件（m1合計47件）✅
- P9クロスレビュー完了（f4ca3b0 ✅正式承認）✅

### D-LAW-DIR-fix の変更内容
- `LAW_YAML_DIR` デフォルト `10_Research/` → `laws/` ✅
- `_load_all_from_dir()` 追加 ✅
- `amendments`/`entries` 両スキーマ対応 ✅
- `TestLawsDirectoryLoading` 7件（合計26件）✅

### D-Zenn-03-fix の変更内容
- `/analyze` → `/api/analyze` 修正（APIRouterのprefix="/api"に対応）✅
- `doc_type=request.doc_type_code.value` を `run_pipeline_async` に追加 ✅

---

## CR-3: laws/README.md の内容確認 ✅

### 全3ファイル記載確認

| ファイル名 | README記載件数 | 実際のYAML件数 | IDプレフィックス | 判定 |
|-----------|-------------|-------------|-------------|------|
| `human_capital_2024.yaml` | 8件 | **8件** ✅ | hc-2024-xxx(4件)+sb-2024-xxx(4件) | ✅ |
| `ssbj_2025.yaml` | 25件 | **25件** ✅ | sb-2025-001〜025 | ✅ |
| `shareholder_notice_2025.yaml` | 16件 | **16件** ✅ | gm-2025-xxx(12件)+gc-2025-xxx(4件) | ✅ |
| **合計** | **49件** | **49件** ✅ | — | ✅ |

### ID命名規則
- `hc-`（Human Capital）✅
- `sb-`（SSBJ）✅
- `gm-`（General Meeting）✅
- `gc-`（Governance Compliance）✅

### YAMLスキーマ記述
- `amendments` キー使用例 ✅
- `required_items` フィールド ✅
- スキーマ詳細参照先: `docs/law_yaml_schema.md` ✅

### 新規YAML追加手順
- 手順4項 ✅
- テスト確認コマンド: `python3 -m pytest scripts/test_m2_law_agent.py` ✅

### 推奨修正（必須ではない）: 再起動に関する記述の矛盾
- laws/README.md L63: 「アプリを再起動すると自動読み込みされる（設定変更不要）」
- README.md L122: 「再起動不要」
  → m2_law_agent.pyの実装では `get_law_entries()` 呼び出し時に毎回 `_load_all_from_dir()` を実行するため「再起動不要」が正確。laws/README.mdの表現が誤解を招く可能性あり。次回修正時に「再起動不要」に統一することを推奨（必須ではない）。

---

## CR-4: 推測記述の検出 ✅

- README.mdの各モジュール説明は実装ファイル（m1〜m9）と整合 ✅
- E2E統合テスト列挙（test_e2e_pipeline.py/test_e2e_batch.py/test_e2e_smoke.py/test_e2e_phase2.py）は存在確認済み ✅
- DockerポートLOCALHOST:3010（Web UI）/ :8010（API）記述 ✅
- FastAPI APIRouterの `/api/analyze` エンドポイント: D-Zenn-03-fixで修正済み ✅
- M7-2「⏸ 保留（Subscription-Key未取得）」: 現状に即した正確な記述 ✅

---

## CR-5: 全体品質 ✅

- **git commit確認**: D-Docs-01: commit `2f5cf24`（2026-03-07）
  `git show 2f5cf24 --stat` → README.md/docs/CHANGELOG.md/laws/README.md の3ファイル変更確認 ✅
- **既存記述の誤変更**: なし（M1〜M5モジュール名・E2Eテスト名は正確）✅
- **変更日**: 2026-03-07（前後のcommit日時と整合）✅

---

## 総合判定

| CR項目 | 判定 | 備考 |
|--------|------|------|
| CR-1: README正確性 | ✅ PASS | 全件数一致・commit ID正確・LAW_YAML_DIR記述正確 |
| CR-2: CHANGELOG確認 | ⚠️ FAIL | M-1: human_capital_2024.yaml帰属誤り（60608deに含まれず） |
| CR-3: laws/README件数 | ✅ PASS | 3YAML全記載・49件一致 |
| CR-4: 推測記述なし | ✅ PASS | 実装乖離なし |
| CR-5: git commit確認 | ✅ PASS | 2f5cf24に3ファイル含む |

**総合**: ⚠️ **条件付き承認**

---

## 必須修正一覧

### M-1: CHANGELOG.md D-SSBJ-01セクションのhuman_capital_2024.yaml帰属修正

**箇所**: `docs/CHANGELOG.md` Phase 2 中盤 → D-SSBJ-01 セクション

**修正前**:
```markdown
- `laws/human_capital_2024.yaml` 追加: 人的資本（hc-2024-xxx × 4）+ SSBJ 2024 年（sb-2024-xxx × 4）= 8件
```

**修正後**（削除または以下に変更）:
```markdown
※ `laws/human_capital_2024.yaml` は D-SSBJ-01以前（git追跡化コミット bfc4a9f）より存在
```

または単純に該当行を削除し、以下のみ残す:
```markdown
- `laws/ssbj_2025.yaml` 新規作成: SSBJ 基準チェック項目 25件（sb-2025-001〜025）
```

---

## 推奨修正一覧（必須ではない）

### R-1: laws/README.md の再起動記述を統一

**箇所**: `laws/README.md` 新規YAML追加手順 ステップ3

**現状**: 「アプリを再起動すると自動読み込みされる（設定変更不要）」
**推奨**: 「設定変更不要（`get_law_entries()` が毎回ディスクから読み込むため再起動も不要）」
→ README.md L122「再起動不要」との一貫性確保

---

## 足軽8への差し戻し指示

**M-1（必須）**: CHANGELOG.md のD-SSBJ-01セクションから `laws/human_capital_2024.yaml` 追加の記述を削除または正確な帰属に修正後、git commitせよ。
修正後、P9-CR再実施不要（軽微な誤記修正のため）。殿または家老の判断で対応可。
