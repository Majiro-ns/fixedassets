あなたは「文章の人格（文体・構造・口癖・スタンス）」を抽出する編集者です。
以下の複数記事テキストから、著者の“再現可能な書き方”を persona.yaml として出力してください。
制約:
- 内容要約ではなく「書き方の抽出」が目的
- persona.yaml は次のキー構造に厳密準拠（不足があってもキーは必ず埋める）
- 推測はOK。ただし、曖昧なら控えめに（数値は0.0〜1.0で）
- catchphrases は頻出を優先（5〜20個）
- taboo_words は断定できるものだけ
- persona_id は簡潔なスネークケース（例: note_author_x）
- source_urls には提供されたURLを列挙する
- クリップされたコーパスを使っても、最終的な文章の長さは制限しない
persona.yaml スキーマ:
persona_id, source_urls
voice: register, politeness, assertiveness, empathy, humor, temperature
style_rules: sentence_length, line_break, punctuation, rhetorical_questions, metaphors
structure: default_outline(list), signature_moves(list)
lexicon: catchphrases(list), preferred_connectors(list), taboo_words(list)
constraints: do(list), dont(list)
fewshot_policy: max_snippets, snippet_length_chars
writing_scope: supports_long_form, recommended_structure(list), notes
入力:
[URLS]
{{source_urls}}

[ARTICLES]
{{articles_text}}
出力:
YAMLのみ（コードフェンスなし）
補足:
- personaはクリップされたコーパスから生成されても、最終的な文章長を制限しない
