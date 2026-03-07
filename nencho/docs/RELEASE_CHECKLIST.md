# リリース・公開前チェックリスト

git push やタグ打ちの前に確認する項目です。初回公開・以降のリリースの両方で使えます。

---

## 1. 公開前（必須）

- [ ] **LICENSE** がリポジトリルートにある
- [ ] **LICENSE** の著作権者（1 行目）を必要に応じて修正（例: `Copyright (c) 2025 あなたの名前`）
- [ ] **README.md** に想定ユーザー・非対応・免責・インストール方法が書かれている
- [ ] **.gitignore** に `nencho.db`、`*.nchbk`、`output/`、`security_settings.json`、`.env` が含まれている
- [ ] コード・ドキュメントに**パスワード・API キー・実在の個人情報**が含まれていない
- [ ] **テストが通る**: `PYTHONPATH=. python -m pytest tests/ -q`

---

## 2. 公開前（推奨）

- [ ] **SECURITY.md** がある（脆弱性報告方法・データ取り扱いの記載）
- [x] README の `npx skills add Majiro-ns/nencho` にリポジトリ所有者を設定済み
- [ ] 単体リポで公開する場合、**clone 用 URL** と **npx skills add** の例を実際のリポ URL に合わせている
- [ ] （任意）**CONTRIBUTING.md** で PR の流れを 1 ページで記載
- [ ] （任意）**.github/workflows** で pytest を実行する CI を設定

---

## 3. 税制・仕様の確認（任意だが推奨）

- [ ] **基礎控除**の高所得区分（655万超〜2400万/2350万）の閾値を国税庁・施行令で確認し、コードまたは README に根拠を 1 行追記
- [ ] **対応年度**（令和7年分のみ / 令和8年分追加等）が README または capabilities に明記されている
- [ ] 新年度対応時: `TaxYear` と各計算モジュールの定数・分岐を税制に合わせて更新した

---

## 4. リリース作業メモ

- タグを打つ場合: `git tag -a v1.0.0 -m "初回リリース"` など
- CHANGELOG を更新する場合: 日付・バージョン・変更概要を追記

---

## 5. 参照

- 詳細なレビュー結果: [OSS_READINESS_REVIEW.md](OSS_READINESS_REVIEW.md)
- 実務上の不足点・疑問点: [PRACTICAL_GAPS_AND_QUESTIONS.md](PRACTICAL_GAPS_AND_QUESTIONS.md)
