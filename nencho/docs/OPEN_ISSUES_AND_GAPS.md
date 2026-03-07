# nencho OSS の不足点・課題一覧

現在の nencho で把握している不足点と課題です。優先度順に整理しています。

---

## 対応済み

| 項目 | 備考 |
|------|------|
| ルート .gitignore | 追加済み（nencho.db, *.nchbk, output/, .env 等） |
| LICENSE（MIT） | リポジトリルートに追加済み |
| SECURITY.md | 脆弱性報告・データ取り扱いを記載済み |
| README のプレースホルダー | `npx skills add Majiro-ns/nencho` に設定済み |

---

## 高優先度（早めに対応したい）

| 項目 | 内容 | 推奨対応 |
|------|------|----------|
| **基礎控除の閾値** | `src/core/calculation/deductions.py` に「655万超 ≤ 2400万」で **2350万 or 2400万要確認** のコメントあり。 | 国税庁・施行令で確認し、コードとコメントを確定。 |
| **単体リポ公開時の URL** | ✅ 対応済。README の clone・`npx skills add` の例を `Majiro-ns` に設定済み。 | 完了。 |

---

## 中優先度（品質・信頼性のため）

| 項目 | 内容 | 推奨対応 |
|------|------|----------|
| **CI（GitHub Actions）** | `.github/workflows` がなく、push 時の自動テスト・lint がない。 | `pytest`（＋必要なら `ruff`）を実行する workflow を追加。 |
| **令和8年分の未対応** | `TaxYear` は R7（令和7年）のみ。令和8年分は未実装。 | 税制確定後に `TaxYear.R8` と各計算モジュールの分岐を追加。README に「令和7年分を正式対応」と明記済み。 |
| **API リクエスト例** | 各ルーターの Pydantic モデルはコード内のみ。README から「どの body を送るか」を一覧で参照しづらい。 | README に `POST /api/calculate` 等のリクエスト例を 1〜2 本追加するか、`docs/api_examples.md` を作成。 |
| **CSV/Excel 取込フォーマット** | テンプレート取得 API はあるが、必須列・サンプルの説明が README にない。 | 取込用 CSV/Excel の必須列とサンプルを docs に追加。 |

---

## 低優先度・任意

| 項目 | 内容 | 推奨対応 |
|------|------|----------|
| **CONTRIBUTING.md** | PR の流れ・ブランチ方針がドキュメント化されていない。 | 短い CONTRIBUTING.md を追加。 |
| **CHANGELOG** | バージョンごとの変更履歴がない。 | 初回は「1.0.0 初回リリース」の 1 行でも可。 |
| **従業員の更新 API** | 従業員マスタの「更新」用 API が明示的でない（扶養の追加・削除では `save_employee` で更新されるが、氏名・給与収入等の一括更新は CLI の import や手動で DB を触る想定）。 | 必要なら `PUT /api/employees/{id}` を検討。README に「更新は再取込または〜」と明記しても可。 |
| **バリデーションの範囲** | 基本項目・扶養・控除試算まで。様式上の必須項目や e-Tax 用の細かいチェックは未定義。 | どのレベルまで「提出可能」とみなすかを capabilities に明記。必要ならチェック項目一覧を docs に追加。 |
| **税額の外部突合** | freee 等との実データ突合は未実施。 | 時間があれば 1 パターンでも突合し「検証済み」を README に記載。 |
| **PDF/Excel 様式の明記** | 令和7年分に準拠している旨はコメントにあるが、様式番号・様式名が README にない。 | 「国税庁 ○○様式 令和7年分 給与所得の源泉徴収票 に準拠」等を 1 行追記。 |
| **住宅ローン控除の入力説明** | 初年度・2年目以降の入力方法が README にない。 | `housing_entry_year` 等と「何年目か」の対応を README または capabilities に短く記載。 |
| **Claude Code プラグイン** | shinkoku には `.claude-plugin/` がある。nencho には未整備。 | スキルのみで十分なら不要。必要に応じてプラグイン化。 |
| **troubleshooting** | よくあるエラー（年末調整対象外の ValueError 等）と対処が一覧化されていない。 | `docs/troubleshooting.md` を追加してもよい。 |

---

## 税制・法令まわり（継続対応）

| 項目 | 内容 |
|------|------|
| 令和9年以降 | 基礎控除の上乗せ特例は令和7・8年分の措置。令和9年分以降は法改正に合わせてルール追加が必要。 |
| R7 以外の入力 | `tax_year != 7` のときは「試算値」として警告。他年度は計算式が未実装のため結果の保証なし。 |

---

## 参照

- 詳細な実務上の不足点・疑問点: [PRACTICAL_GAPS_AND_QUESTIONS.md](PRACTICAL_GAPS_AND_QUESTIONS.md)
- 公開前チェック: [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)
- OSS 公開可否レビュー: [OSS_READINESS_REVIEW.md](OSS_READINESS_REVIEW.md)
