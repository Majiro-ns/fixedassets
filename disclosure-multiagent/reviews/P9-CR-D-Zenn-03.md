# P9-CR-D-Zenn-03: disclosure記事③（招集通知）クロスレビュー

**レビュアー**: 足軽8
**対象**: `docs/article_disclosure_shoshu_draft.md`（足軽7作成）
**実施日**: 2026-03-09
**参照実装**: scripts/m1_pdf_agent.py / laws/shareholder_notice_2025.yaml / api/models/schemas.py / api/routers/analyze.py / api/services/pipeline.py / tests/test_shoshu.py

---

## 再CR結果（commit 0dde91a / 2026-03-09）

**✅ 正式承認（M1・M2必須修正 全件解消確認）**

| 修正 | 内容 | 解消確認 |
|------|------|---------|
| M1 | FastAPI URL: `/analyze` → `/api/analyze` | ✅ 記事 Section 5-1 修正済み |
| M2 | `run_pipeline_async` に `doc_type` 引き渡し | ✅ analyze.py + pipeline.py 実装追加 + extract_report引き渡し確認 |

#### M1修正詳細確認
```diff
- "http://localhost:8000/analyze",
+ "http://localhost:8000/api/analyze",
```
記事 Section 5-1のURLが正確に修正されている。 ✅
説明文に「APIルーターが `doc_type_code` をパイプラインに引き渡し、M1の `extract_report()` が招集通知モードで実行される。」の注釈追加も適切。 ✅

#### M2修正詳細確認
```python
# api/routers/analyze.py
doc_type=request.doc_type_code.value,  # DocTypeCode(str,Enum)の.valueで文字列取得 ✅

# api/services/pipeline.py
async def run_pipeline_async(..., doc_type: str = "yuho") -> None:
    ...
    extract_report(..., doc_type=doc_type)  # extract_report(doc_type: str = "yuho")と一致 ✅
```

- `DocTypeCode(str, Enum)` の `.value` は "yuho"/"shoshu" 文字列を返す ✅
- `extract_report` の `doc_type: str = "yuho"` シグネチャと一致 ✅
- デフォルト値 `doc_type: str = "yuho"` により後方互換維持 ✅

---

## 総合判定（初回）

**⚠️ 条件付き承認（必須修正2件・推奨修正1件）**

必須修正（M1〜M2）を修正後、再コミット → 再CR不要で承認。

---

## CR-1: 技術的正確性チェック

### 判定: ✅ PASS

#### doc_type="shoshu"の引数設計
記事掲載のシグネチャと実装を直接照合した。

| 関数 | 記事 | m1_pdf_agent.py（実装） | 判定 |
|------|------|----------------------|------|
| `split_sections_from_text` | `doc_type: str = "yuho"` | line 147/150: `doc_type: str = "yuho"` | ✅ |
| `_is_heading_line_for_doc_type` | `doc_type: str = "yuho"` | line 129: `doc_type: str = "yuho"` | ✅ |
| `get_shoshu_sections` | `report: StructuredReport` | line 450: `report: StructuredReport` | ✅ |

#### SHOSHU_SECTION_KEYWORDS（12件）
- 記事: 12件列挙 ✅
- 実装: m1_pdf_agent.py line 72 `SHOSHU_SECTION_KEYWORDS` 存在 ✅
- テスト: `test_total_keyword_count_is_12` でカウント保証 ✅

#### SHOSHU_HEADING_PATTERNS（8件）
- 記事: 8パターン掲載 ✅
- 実装: m1_pdf_agent.py line 88 `SHOSHU_HEADING_PATTERNS` 存在 ✅
- テスト: `test_heading_patterns_count_is_8` でカウント保証 ✅

#### DocTypeCode enum（schemas.py照合）
記事のコードと`api/models/schemas.py`の実装が完全一致:
```python
class DocTypeCode(str, Enum):
    yuho = "yuho"      # ✅
    shoshu = "shoshu"  # ✅
```
`EdinetDocument.doc_type_code: str`（EDINET数値コード）と`AnalyzeRequest.doc_type_code: DocTypeCode`（セマンティックコード）の型分離説明も正確。 ✅

#### 16項目チェックリスト（gm12+gc4）— laws/shareholder_notice_2025.yaml照合

**総会前開示（gm）12件: ✅ 全件一致**

| 記事の法令根拠 | YAML実装 | 判定 |
|-------------|---------|------|
| gm-2025-001: 会社法第325条の2 | 改正会社法第325条の2〜325条の7 | ✅ |
| gm-2025-002: 会社法第299条 | 会社法第299条 | ✅ |
| gm-2025-003: CGコード補充原則1-2④ | CGコード補充原則1-2④ | ✅ |
| gm-2025-004: CGコード補充原則1-2④ | CGコード補充原則1-2④ | ✅ |
| gm-2025-005: 会社法施行規則第74条 | 第74条・74条の3 | ✅ |
| gm-2025-006: CGコード原則4-9 | 原則4-9 | ✅ |
| gm-2025-007: 会社法施行規則第82条 | 第82条・82条の2 | ✅ |
| gm-2025-008: 会社法施行規則第76条 | 第76条・76条の2 | ✅ |
| gm-2025-009: 会社法施行規則第85条 | 第85条 | ✅ |
| gm-2025-010: 会社法第305条 | 第304条・305条 | ✅ |
| gm-2025-011: 上場規程第415条 | 東証上場規程第415条 | ✅ |
| gm-2025-012: 有価証券報告書改革 | 有報改革（FSA） | ✅ |

**ガバナンス（gc）4件: ✅ 全件一致**

| ID | 記事タイトル | YAML | 判定 |
|----|------------|------|------|
| gc-2025-001 | スキルマトリックス | CGコード補充原則4-11① | ✅ |
| gc-2025-002 | 取締役会評価 | CGコード補充原則4-11③ | ✅ |
| gc-2025-003 | 政策保有株式方針 | CGコード原則1-4 | ✅ |
| gc-2025-004 | サステナビリティ連動型役員報酬 | 有報改革・サステナ開示義務化 | ✅ |

gc-2025-004の「SSBJ対応との連携項目」説明は、YAMLのサステナビリティ開示義務化との関連として妥当。 ✅

---

## CR-2: コードスニペット検証

### 判定: ⚠️ 必須修正2件

#### ✅ PASS: doc_type分岐ロジック

記事掲載コード:
```python
patterns = SHOSHU_HEADING_PATTERNS if doc_type == "shoshu" else HEADING_PATTERNS
return any(p.search(stripped) for p in patterns)
```
m1_pdf_agent.py line 129付近の`_is_heading_line_for_doc_type`実装と一致。 ✅

#### ✅ PASS: 後方互換設計の3原則

「原則1: デフォルト引数は"yuho"」「原則2: 既存関数は変更しない」「原則3: 既存テスト32件PASS」の記述は実装と一致。 ✅

#### ❌ M1: FastAPIエンドポイントURL誤り（必須修正）

**記事 Section 5-1:**
```python
response = httpx.post(
    "http://localhost:8000/analyze",   # ← 誤り
    ...
)
```

**実装（api/routers/analyze.py）:**
```python
router = APIRouter(prefix="/api", tags=["analyze"])  # prefix="/api"

@router.post("/analyze", ...)  # → 実際のパス: /api/analyze
```

**正しいURL**: `http://localhost:8000/api/analyze`

`/analyze` は存在しない。`/api` プレフィックスが抜けている。

#### ❌ M2: run_pipeline_asyncにdoc_type未引き渡し（必須修正）

記事では「`doc_type_code: "shoshu"` を指定するだけで、M1〜M5が全て招集通知向けの処理に切り替わる」と主張。しかし実際のanalyze.pyとpipeline.pyを確認すると:

**api/routers/analyze.py（実装）:**
```python
background_tasks.add_task(
    run_pipeline_async,
    task_id=task_id,
    pdf_path=pdf_path,
    company_name=company_name,
    fiscal_year=request.fiscal_year,
    fiscal_month_end=request.fiscal_month_end,
    level=request.level,
    use_mock=request.use_mock,
    # ← request.doc_type_code が渡されていない！
)
```

**api/services/pipeline.py（実装）:**
```python
async def run_pipeline_async(
    task_id: str,
    pdf_path: str,
    company_name: str,
    fiscal_year: int,
    fiscal_month_end: int,
    level: str,
    use_mock: bool = True,
    # ← doc_type パラメータが存在しない！
) -> None:
```

`run_pipeline_async` は `doc_type` を受け付けず、内部の `extract_report()` も `doc_type` なしで呼び出されている。つまり、APIから `doc_type_code: "shoshu"` を指定しても、実際のM1処理は有報モード（`doc_type="yuho"` デフォルト）で動作する。

記事の記述「M1〜M5が全て招集通知向けの処理に切り替わる」は現状の実装では成立しない。

**修正指示**: Section 5-1のコードスニペットに注釈を追加し、または「現在のAPIは`doc_type_code`をパイプラインに引き渡す実装が未完成。直接m1_pdf_agent.pyを呼び出す場合のみ`doc_type="shoshu"`が有効」と正確に記述すること。

---

## CR-3: 法令根拠の正確性

### 判定: ✅ PASS

#### 会社法・CGコード条項引用

| 記事の引用 | 正確性 | 備考 |
|-----------|--------|------|
| 改正会社法 第325条の2〜325条の7 | ✅ | 電子提供制度の正確な条文範囲 |
| 会社法第299条 | ✅ | 招集通知発送義務の根拠条文 |
| 会社法施行規則第74条 | ✅ | 取締役選任（主要条文のみ引用で可） |
| 会社法施行規則第76条 | ✅ | 監査役選任（主要条文のみ引用で可） |
| 会社法施行規則第82条 | ✅ | 役員報酬議案 |
| 会社法施行規則第85条 | ✅ | 定款変更議案 |
| 会社法第305条 | ✅ | 株主提案権（304条も根拠だが305条で可） |
| 上場規程第415条 | ✅ | 議決権行使結果開示 |
| CGコード補充原則1-2④ | ✅ | 早期発送・英語版・電子行使 |
| CGコード補充原則4-11① | ✅ | スキルマトリックス義務化 |
| CGコード原則4-9 | ✅ | 独立性基準の制定・開示 |

#### gm/gc分類の正確性
- gm（general meeting：総会前開示）12件、gc（governance：ガバナンス）4件 ✅
- 分類根拠の説明（gm=招集通知基本要件、gc=CGコード対応要件）正確 ✅

#### gc-2025-004（SSBJ連動報酬）の記述
- 「SSBJ（サステナビリティ基準委員会）対応と連携した項目」の表現はYAML内の「2024年3月期からのサステナビリティ開示義務化との整合」と整合 ✅
- CO2削減・女性管理職比率・エンゲージメントスコア等のKPI例もYAML記述と一致 ✅

---

## CR-4: 記事構成の確認

### 判定: ✅ PASS（推奨修正1件）

#### 7節構成の確認

| 節 | タイトル | 存在 |
|----|---------|------|
| 1 | なぜ招集通知の法令チェックが重要か | ✅ |
| 2 | 書類種別拡張アーキテクチャ | ✅ |
| 3 | 招集通知チェック項目（shareholder_notice_2025.yaml） | ✅ |
| 4 | 実装コード | ✅ |
| 5 | M2〜M5パイプラインによる法令照合・ギャップ分析・改善提案 | ✅ |
| 6 | テスト設計（TestShoshuDocType パターン） | ✅ |
| 7 | まとめ | ✅ |

7節構成完備 ✅

#### 松竹梅提案例とM4 FEW_SHOT_EXAMPLESの照合

記事 Section 5-3に「M4松竹梅提案の出力サンプル」として梅/竹/松の提案例を掲載。
m4_proposal_agent.pyを確認したところ、**shoshu専用のFEW_SHOT_EXAMPLESエントリは存在しない**（grep: "shoshu" → No matches）。

ただし記事では「出力サンプル」として概念的な例を示しており、実際のFEW_SHOT_EXAMPLES dictとして提示していない。実装上の問題というよりshoshu対応のFEW_SHOT_EXAMPLESが未実装であることの説明不足。

**推奨修正R1**: Section 5-3に注釈追加。「現在のM4は有報向けFEW_SHOT_EXAMPLES（SSBJ/HC sections）を保有しているが、shoshu向けFEW_SHOT_EXAMPLESは未実装。shoshu処理時はLLMが直接few-shot例なしで提案を生成する（またはモック応答）」と明記することで、読者の実装期待値を正しく設定できる。

---

## CR-5: 文章品質・要件確認

### 判定: ✅ PASS

#### 字数確認
- **15,761字**（frontmatter除く）→ 8,000字以上 ✅（要件の約2倍）

#### Zenn frontmatter確認
```yaml
---
title: "AIで株主総会招集通知の法令チェックを自動化する — disclosure-multiagentの書類種別拡張"
emoji: "📋"
type: "tech"
topics: ["python", "ai", "コーポレートガバナンス", "株主総会"]
published: false
---
```
全フィールド揃っている ✅

---

## 必須修正サマリー

| No | 場所 | 問題 | 修正指示 |
|----|------|------|---------|
| M1 | Section 5-1 コードスニペット | FastAPI URL誤り（`/analyze` → `/api/analyze`） | `http://localhost:8000/api/analyze` に修正 |
| M2 | Section 5-1 説明文 | `doc_type_code: "shoshu"` がパイプラインに引き渡されない実装事実を誤表現 | 「APIから直接shoshu指定する場合は`run_pipeline_async`の`doc_type`未引き渡し問題あり（実装TODO）」と注釈追加、または正確な動作説明に修正 |

## 推奨修正サマリー

| No | 場所 | 提案 |
|----|------|------|
| R1 | Section 5-3 | shoshu向けFEW_SHOT_EXAMPLESが未実装である旨を注釈追加 |

---

## 知見共有

- **FastAPI prefix注意**: `APIRouter(prefix="/api")` を使う場合、記事のサンプルURLは常に `/api/<endpoint>` になる。コードスニペット記事では特に誤りやすい
- **pipeline.py doc_type引き渡し**: `AnalyzeRequest.doc_type_code` がAPIで受け取れても、`run_pipeline_async` に伝達しなければM1は常にyuhoモードで動作する。shoshu対応を完全に有効化するにはpipeline.pyの改修が必要
- **M4 FEW_SHOT_EXAMPLES**: SSBJ/HC sections向けのみ実装。shoshu向けは未実装のため、記事の松竹梅サンプルはLLMが生成する概念例であることを明記すべき
