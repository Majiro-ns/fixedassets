目的: 文体模倣に効く原文断片を intro/body/ending に分散させて抽出する。
出力: 厳密JSONのみ（前後の文字禁止、コードフェンス禁止）。
制約:
- 断片長: 250-600文字
- 最大6個、最低3個
- 口調・改行・接続詞・比喩・言い回しの特徴が伝わる部分を優先
- 固有名詞や日付は避け、一般化できる箇所を選ぶ
- intro/body/ending が偏らないようにする
JSONスキーマ（順序通り）:
{
  "snippets": [
    {
      "label": "intro|body|ending",
      "text": "原文抜粋",
      "source_url": "元URL",
      "why": "この断片が文体把握に役立つ理由"
    }
  ]
}
入力:
persona:
{{persona_yaml}}

source_urls:
{{source_urls}}

articles:
{{articles_text}}
