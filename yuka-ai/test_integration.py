#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yuka-ai 統合テストスクリプト

全モジュールの連携を検証する:
  1. SQLiteスキーマ初期化
  2. 品番登録 + 価格記録
  3. 価格推移・アラートチェック
  4. 発注書Excel生成
  5. 交渉メール生成
  6. ミスミクライアント（モック）
  7. 統合フロー: 手動入力 → DB → アラート → メール → Excel
"""
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# プロトタイプディレクトリをパスに追加
sys.path.insert(0, str(Path(__file__).parent))


def test_schema_init():
    """テスト1: SQLiteスキーマ初期化"""
    print("=" * 60)
    print("テスト1: SQLiteスキーマ初期化")
    print("=" * 60)

    from price_tracker import init_db
    db_file = os.path.join(tempfile.gettempdir(), "yuka_test.db")

    conn = init_db(db_file)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='view' ORDER BY name")
    views = [r[0] for r in cur.fetchall()]

    expected_tables = [
        "delivery_tracking", "email_log", "inventory", "negotiations", "parts",
        "price_alerts", "price_history", "purchase_order_items", "purchase_orders", "suppliers",
    ]
    expected_views = ["v_latest_prices", "v_price_alerts"]

    # sqlite_sequence は自動生成されるためフィルタ
    app_tables = [t for t in tables if t != "sqlite_sequence"]

    assert set(expected_tables) == set(app_tables), f"Tables mismatch: {app_tables}"
    assert set(expected_views) == set(views), f"Views mismatch: {views}"

    print(f"  テーブル: {len(app_tables)}件 OK")
    print(f"  ビュー: {len(views)}件 OK")

    conn.close()
    os.unlink(db_file)
    print("  PASS\n")
    return True


def test_price_tracking():
    """テスト2: 品番登録 + 価格記録 + アラートチェック"""
    print("=" * 60)
    print("テスト2: 品番登録 + 価格記録 + アラートチェック")
    print("=" * 60)

    from price_tracker import (
        init_db, record_price, get_latest_price,
        get_price_history, check_alerts, format_alert_message,
    )
    db_file = os.path.join(tempfile.gettempdir(), "yuka_test2.db")
    conn = init_db(db_file)

    # 品番A: 3回の価格変動（+10.1% → CRITICAL）
    record_price(conn, "SCS8", 850, "misumi", "リニアシャフト φ8")
    record_price(conn, "SCS8", 890, "misumi", "リニアシャフト φ8")
    record_price(conn, "SCS8", 980, "misumi", "リニアシャフト φ8")

    # 品番B: 安定（+1.6% → OK, アラートなし）
    record_price(conn, "SSEBZ6", 15, "misumi", "六角穴付きボルト M6")
    record_price(conn, "SSEBZ6", 15, "misumi", "六角穴付きボルト M6")
    record_price(conn, "SSEBZ6", 15.25, "misumi", "六角穴付きボルト M6")

    # 品番C: 値下がり（-5.6% → WARNING）
    record_price(conn, "SHKLBR10", 800, "misumi", "リニアブッシュ φ10")
    record_price(conn, "SHKLBR10", 780, "misumi", "リニアブッシュ φ10")
    record_price(conn, "SHKLBR10", 736, "misumi", "リニアブッシュ φ10")

    # 最新価格チェック
    latest = get_latest_price(conn, "SCS8")
    assert latest is not None, "SCS8 not found"
    assert latest["latest_price"] == 980, f"Expected 980, got {latest['latest_price']}"
    assert latest["prev_price"] == 890, f"Expected prev 890, got {latest['prev_price']}"
    assert abs(latest["change_pct"] - 10.1) < 0.2, f"change_pct: {latest['change_pct']}"
    print(f"  SCS8 最新価格: ¥{latest['latest_price']:,.0f} (前回比: {latest['change_pct']:+.1f}%) OK")

    # 履歴チェック
    history = get_price_history(conn, "SCS8")
    assert len(history) == 3, f"Expected 3 history records, got {len(history)}"
    print(f"  SCS8 履歴: {len(history)}件 OK")

    # アラートチェック
    alerts = check_alerts(conn)
    assert len(alerts) >= 2, f"Expected ≥2 alerts, got {len(alerts)}"

    critical_alerts = [a for a in alerts if a.alert_level == "CRITICAL"]
    warning_alerts = [a for a in alerts if a.alert_level == "WARNING"]
    assert len(critical_alerts) >= 1, "Missing CRITICAL alert for SCS8"
    assert len(warning_alerts) >= 1, "Missing WARNING alert for SHKLBR10"

    print(f"  アラート: {len(alerts)}件（CRITICAL={len(critical_alerts)}, WARNING={len(warning_alerts)}）")
    for a in alerts:
        print(f"    {format_alert_message(a)}")

    conn.close()
    os.unlink(db_file)
    print("  PASS\n")
    return True


def test_purchase_order():
    """テスト3: 発注書Excel生成"""
    print("=" * 60)
    print("テスト3: 発注書Excel生成")
    print("=" * 60)

    from purchase_order_template import (
        PurchaseOrder, Supplier, LineItem, generate_purchase_order,
    )

    po = PurchaseOrder(
        po_number="PO-TEST-001",
        issue_date="2026年2月8日",
        delivery_date="2026年2月28日",
        delivery_location="本社倉庫",
        supplier=Supplier(name="ミスミ", contact_person="テスト担当"),
        items=[
            LineItem(1, "SCS8", "リニアシャフト φ8", 10, "本", 320),
            LineItem(2, "SHKLBR10", "リニアブッシュ φ10", 5, "個", 780),
            LineItem(3, "SSEBZ6-25", "六角穴付きボルト M6×25", 100, "本", 15),
        ],
        company_name="テスト工業株式会社",
    )

    output_file = os.path.join(tempfile.gettempdir(), "test_po.xlsx")
    result = generate_purchase_order(po, output_file)

    assert os.path.exists(result), f"Excel not created: {result}"
    file_size = os.path.getsize(result)
    assert file_size > 1000, f"Excel too small: {file_size} bytes"

    print(f"  ファイル: {result}")
    print(f"  サイズ: {file_size:,} bytes")
    print(f"  合計金額（税込）: ¥{po.grand_total:,.0f}")
    print(f"  明細: {len(po.items)}件")

    os.unlink(result)
    print("  PASS\n")
    return True


def test_negotiation_emails():
    """テスト4: 交渉メール生成"""
    print("=" * 60)
    print("テスト4: 交渉メール生成3パターン")
    print("=" * 60)

    from negotiation_emails import (
        NegotiationContext,
        generate_volume_discount,
        generate_long_term,
        generate_competitor_quote,
    )

    ctx = NegotiationContext(
        supplier_name="ミスミ", contact_person="山田",
        my_company_name="テスト工業", my_name="鈴木",
        my_department="資材課", part_number="SCS8",
        part_description="リニアシャフト φ8",
        current_price=980, target_price=900,
        quantity=50, annual_quantity=600,
        competitor_price=850, contract_years=2, relationship_years=3,
    )

    for label, fn in [("数量割引", generate_volume_discount),
                       ("長期契約", generate_long_term),
                       ("競合見積", generate_competitor_quote)]:
        email = fn(ctx)
        assert "subject" in email, f"Missing subject in {label}"
        assert "body" in email, f"Missing body in {label}"
        assert len(email["body"]) > 100, f"{label} body too short"
        assert "ミスミ" in email["body"], f"{label} missing supplier name"
        assert "SCS8" in email["body"], f"{label} missing part number"
        print(f"  {label}: {email['subject']} ({len(email['body'])}文字) OK")

    print("  PASS\n")
    return True


def test_misumi_client_structure():
    """テスト5: ミスミクライアント構造チェック"""
    print("=" * 60)
    print("テスト5: ミスミクライアント構造チェック")
    print("=" * 60)

    from misumi_client import (
        MisumiProduct, MisumiRequestsClient, MisumiClient,
        ManualPriceEntry, manual_price_to_product, _extract_price,
    )

    # データモデルテスト
    product = MisumiProduct(
        series_code="110300465660", part_number="SCS8",
        product_name="リニアシャフト", unit_price=320,
        days_to_ship=3,
    )
    assert "SCS8" in str(product)
    assert "¥320" in str(product)
    print(f"  MisumiProduct: {product} OK")

    # 手動入力テスト
    entry = ManualPriceEntry("TEST-001", "テスト品", 1500.0, "manual", "テスト商社")
    converted = manual_price_to_product(entry)
    assert converted.part_number == "TEST-001"
    assert converted.unit_price == 1500.0
    print(f"  ManualPriceEntry → MisumiProduct: OK")

    # 価格抽出テスト
    assert _extract_price("¥1,234") == 1234.0
    assert _extract_price("￥5,678円") == 5678.0
    assert _extract_price("税抜 3,200") == 3200.0
    assert _extract_price("") is None
    assert _extract_price(None) is None
    print(f"  _extract_price: 5パターン OK")

    # クライアント初期化テスト
    client = MisumiClient(use_playwright=False)
    assert client._requests_client is not None
    print(f"  MisumiClient初期化: OK")

    print("  PASS\n")
    return True


def test_integrated_flow():
    """テスト6: 統合フロー（手動入力 → DB → アラート → メール推薦）"""
    print("=" * 60)
    print("テスト6: 統合フロー")
    print("=" * 60)

    from price_tracker import (
        init_db, fetch_and_record_manual, check_alerts, format_alert_message,
    )
    from negotiation_emails import (
        NegotiationContext, generate_volume_discount,
    )
    from purchase_order_template import (
        PurchaseOrder, Supplier, LineItem, generate_purchase_order,
    )

    db_file = os.path.join(tempfile.gettempdir(), "yuka_integration.db")
    conn = init_db(db_file)

    # Step 1: 手動価格入力（初回）
    print("  Step 1: 初回価格記録")
    fetch_and_record_manual(conn, "SCS8", "リニアシャフト φ8", 850, "misumi")
    print("    SCS8: ¥850 記録完了")

    # Step 2: 価格更新（値上がり）
    print("  Step 2: 価格更新（値上がり ¥850→¥980）")
    result = fetch_and_record_manual(conn, "SCS8", "リニアシャフト φ8", 980, "misumi")
    assert result is not None
    assert result["latest_price"] == 980
    pct = result.get("change_pct")
    print(f"    SCS8: ¥{result['latest_price']:,.0f} (変動率: {pct:+.1f}%)")

    # Step 3: アラートチェック
    print("  Step 3: アラートチェック")
    alerts = check_alerts(conn)
    assert len(alerts) >= 1
    critical = [a for a in alerts if a.alert_level == "CRITICAL"]
    assert len(critical) >= 1, "SCS8 should trigger CRITICAL alert"
    for a in alerts:
        print(f"    {format_alert_message(a)}")

    # Step 4: アラートに基づいて交渉メール生成
    print("  Step 4: 交渉メール自動生成")
    alert = critical[0]
    ctx = NegotiationContext(
        supplier_name="ミスミ", contact_person="担当者",
        my_company_name="サンプル工業", my_name="鈴木",
        my_department="資材課", part_number=alert.part_number,
        part_description=alert.description,
        current_price=alert.latest_price,
        target_price=alert.prev_price,  # 前回価格に戻す目標
        quantity=50, annual_quantity=600,
    )
    email = generate_volume_discount(ctx)
    print(f"    件名: {email['subject']}")
    print(f"    本文: {len(email['body'])}文字")

    # Step 5: 発注書生成
    print("  Step 5: 発注書生成")
    po = PurchaseOrder(
        po_number=f"PO-{datetime.now().strftime('%Y%m%d')}-INT",
        supplier=Supplier(name="ミスミ"),
        items=[LineItem(1, "SCS8", "リニアシャフト φ8", 10, "本", 980)],
        company_name="サンプル工業",
    )
    output_file = os.path.join(tempfile.gettempdir(), "test_integration_po.xlsx")
    generate_purchase_order(po, output_file)
    assert os.path.exists(output_file)
    print(f"    発注書: {output_file} (¥{po.grand_total:,.0f})")
    os.unlink(output_file)

    conn.close()
    os.unlink(db_file)
    print("  PASS\n")
    return True


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main():
    print("\n" + "=" * 60)
    print("  yuka-ai 統合テスト")
    print("=" * 60 + "\n")

    tests = [
        ("スキーマ初期化", test_schema_init),
        ("価格追跡", test_price_tracking),
        ("発注書生成", test_purchase_order),
        ("交渉メール", test_negotiation_emails),
        ("ミスミクライアント", test_misumi_client_structure),
        ("統合フロー", test_integrated_flow),
    ]

    results = []
    for name, test_fn in tests:
        try:
            passed = test_fn()
            results.append((name, "PASS" if passed else "FAIL"))
        except Exception as e:
            print(f"  FAIL: {e}\n")
            results.append((name, f"FAIL: {e}"))

    # サマリ
    print("=" * 60)
    print("  テスト結果サマリ")
    print("=" * 60)
    all_pass = True
    for name, result in results:
        icon = "✅" if result == "PASS" else "❌"
        print(f"  {icon} {name}: {result}")
        if result != "PASS":
            all_pass = False

    passed = sum(1 for _, r in results if r == "PASS")
    total = len(results)
    print(f"\n  {passed}/{total} テスト合格")

    if all_pass:
        print("\n  全テスト合格！yuka-ai プロトタイプは正常に動作しています。")
    else:
        print("\n  一部テスト失敗。上記のエラーを確認してください。")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
