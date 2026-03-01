# PDF解析 PoC

> 様式第19号の有報PDFからテキスト・セクションを抽出する手段の検証。
> 23_Next_Actions_Detail の「2. PDF解析の PoC 実施」に相当。

---

## 1. サンプル確保（先に実施）

EDINET から公開有報 PDF を 3〜5 社取得する。

- **URL**: https://disclosure.edinet-fsa.go.jp/
- **手順**: 書類を検索 → 有価証券報告書 → 企業指定 → PDF ダウンロード
- **選定目安**: スタンダード上場、人的資本記載あり、2023〜2024年提出分
- **保存先**: `10_Research/samples/` に配置（.gitignore に追加推奨）

---

## 2. 環境準備

```bash
cd 10_Projects/disclosure-multiagent
pip install -r requirements_poc.txt
```

---

## 3. 実行

```bash
python scripts/pdf_poc_extract.py 10_Research/samples/
```

---

## 4. 結果

`PDF_PoC_Result.md` に比較結果を追記する。
