#!/usr/bin/env python3
"""
disclosure-multiagent 実API動作確認スクリプト

使い方:
    ANTHROPIC_API_KEY=sk-ant-... python3 check_real_api.py

目的:
    APIキー設定後に即時実LLM確認できる環境を整備する。
    このスクリプトで OK が出た後に run_e2e.py を実行せよ。
"""
import os
import sys


def check_environment() -> bool:
    """APIキーと依存関係を確認"""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("❌ ANTHROPIC_API_KEY が未設定です")
        print("   設定方法: export ANTHROPIC_API_KEY=sk-ant-...")
        return False
    print(f"✅ ANTHROPIC_API_KEY 設定済み（先頭8文字: {api_key[:8]}...）")
    try:
        import anthropic
        c = anthropic.Anthropic()
        r = c.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": "respond: OK"}]
        )
        print(f"✅ API疎通確認: {r.content[0].text}")
        return True
    except ImportError:
        print("❌ anthropic パッケージ未インストール: pip install anthropic")
        return False
    except Exception as e:
        print(f"❌ API呼び出し失敗: {e}")
        return False


def show_run_instructions() -> None:
    """実API実行手順を表示"""
    print("\n=== disclosure 実API E2E 実行手順 ===")
    print("1. export ANTHROPIC_API_KEY=sk-ant-...（殿のAPIキーを設定）")
    print("2. cd scripts/")
    print("3. USE_MOCK_LLM=false python3 run_e2e.py ../10_Research/samples/company_a.pdf")
    print("   → M1〜M5フルパイプライン実LLM動作")
    print("4. 出力を reports/ に確認")
    print("   期待値: M3（ギャップ5件以上）・M4（松竹梅各1提案×ギャップ数）・M5（3000字以上レポート）")
    print("\n評価基準: 10_Research/real_api_eval_criteria.md を参照")


if __name__ == "__main__":
    ok = check_environment()
    show_run_instructions()
    sys.exit(0 if ok else 1)
