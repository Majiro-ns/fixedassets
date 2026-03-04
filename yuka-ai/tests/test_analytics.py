"""tests/test_analytics.py

cmd_285k_yukaai: 価格トレンド分析・発注タイミング推奨のテスト

【検証対象】
  1. analytics_service.compute_price_trend() — 純粋関数のユニットテスト
  2. analytics_service.compute_buy_recommendation() — 純粋関数のユニットテスト
  3. GET /api/analytics/price-trend/{part_number} — API エンドポイント
  4. GET /api/analytics/buy-recommendation/{part_number} — API エンドポイント

【設計方針】
  - analytics_service はDBに依存しない純粋関数 → 直接テスト
  - API テストは既存パターン（TestClient + 一時DB）に従う
"""
from __future__ import annotations

import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from api.services.analytics_service import (
    compute_price_trend,
    compute_buy_recommendation,
)


# ============================================================
# テスト用ヘルパー
# ============================================================

def _history(*prices: float) -> list[dict]:
    """価格リストから価格履歴ダミーデータを生成する（日付は連番）。"""
    return [
        {"price": p, "fetched_at": f"2026-02-{i+1:02d}T10:00:00", "source": "manual"}
        for i, p in enumerate(prices)
    ]


# ============================================================
# ユニットテスト: compute_price_trend
# ============================================================

class TestComputePriceTrend:
    """compute_price_trend の純粋関数テスト"""

    def test_rising_trend(self):
        """上昇トレンド: 100→115（+15%）→ rising"""
        history = _history(100, 105, 108, 115)
        result = compute_price_trend(history)

        assert result["trend_direction"] == "rising"
        assert result["trend_pct"] == pytest.approx(15.0, abs=0.1)
        assert result["latest_price"] == 115
        assert result["min_price"] == 100
        assert result["max_price"] == 115
        assert result["data_points"] == 4
        # CHECK-7b: avg = (100+105+108+115)/4 = 107.0
        assert result["avg_price"] == pytest.approx(107.0, abs=0.1)

    def test_falling_trend(self):
        """下落トレンド: 200→180（-10%）→ falling"""
        history = _history(200, 195, 185, 180)
        result = compute_price_trend(history)

        assert result["trend_direction"] == "falling"
        assert result["trend_pct"] == pytest.approx(-10.0, abs=0.1)
        assert result["latest_price"] == 180
        assert result["data_points"] == 4

    def test_stable_trend(self):
        """安定トレンド: 100→101（+1%、±2%以内）→ stable"""
        history = _history(100, 100, 101, 100)
        result = compute_price_trend(history)

        assert result["trend_direction"] == "stable"
        assert abs(result["trend_pct"]) <= 2.0
        assert result["data_points"] == 4

    def test_single_data_point(self):
        """単一データポイント: トレンド率0、安定"""
        history = _history(500)
        result = compute_price_trend(history)

        assert result["trend_direction"] == "stable"
        assert result["trend_pct"] == 0.0
        assert result["latest_price"] == 500
        assert result["data_points"] == 1
        assert result["volatility_pct"] == 0.0  # 単一点はvolatility計算不可

    def test_empty_history(self):
        """空の履歴: unknown が返る"""
        result = compute_price_trend([])

        assert result["trend_direction"] == "unknown"
        assert result["data_points"] == 0
        assert result["latest_price"] == 0.0

    def test_volatility_calculation(self):
        """ボラティリティ計算: 分散が大きい場合に volatility_pct > 0"""
        # 100と200が交互 → 高ボラティリティ
        history = _history(100, 200, 100, 200)
        result = compute_price_trend(history)

        assert result["volatility_pct"] > 0.0
        # avg=150, stdev≈57.7, volatility≈38.5%
        assert result["volatility_pct"] == pytest.approx(38.5, abs=2.0)


# ============================================================
# ユニットテスト: compute_buy_recommendation
# ============================================================

class TestComputeBuyRecommendation:
    """compute_buy_recommendation の純粋関数テスト"""

    def test_buy_now_rapid_rise(self):
        """急騰（+10%）→ BUY_NOW。さらに値上がりする前に買え"""
        result = compute_buy_recommendation(
            trend_direction="rising",
            trend_pct=10.0,
            current_price=110,
            min_price=100,
            avg_price=105,
        )

        assert result["action"] == "BUY_NOW"
        assert result["score"] > 70
        assert "上昇" in result["reason"] or "上がり" in result["reason"] or "BUY" in result["reason"] or "発注" in result["reason"]

    def test_buy_now_near_min_price(self):
        """底値圏（現在=101, 最安値=100, 1.05倍以内）→ BUY_NOW"""
        result = compute_buy_recommendation(
            trend_direction="stable",
            trend_pct=1.0,
            current_price=101,
            min_price=100,
            avg_price=120,
        )

        assert result["action"] == "BUY_NOW"
        assert result["score"] >= 70
        assert "最安値" in result["reason"] or "底値" in result["reason"]

    def test_wait_falling(self):
        """下落トレンド（-8%）→ WAIT"""
        result = compute_buy_recommendation(
            trend_direction="falling",
            trend_pct=-8.0,
            current_price=92,
            min_price=85,
            avg_price=100,
        )

        assert result["action"] == "WAIT"
        assert result["score"] < 50
        assert "下落" in result["reason"] or "待" in result["reason"]

    def test_neutral_stable(self):
        """安定トレンド（+1%）→ NEUTRAL"""
        result = compute_buy_recommendation(
            trend_direction="stable",
            trend_pct=1.0,
            current_price=101,
            min_price=95,
            avg_price=100,
        )

        assert result["action"] == "NEUTRAL"
        assert result["score"] == pytest.approx(50.0, abs=10.0)

    def test_neutral_gentle_rise(self):
        """緩やかな上昇（+3%）→ NEUTRAL（急騰閾値5%未満）"""
        result = compute_buy_recommendation(
            trend_direction="rising",
            trend_pct=3.0,
            current_price=103,
            min_price=90,
            avg_price=100,
        )

        assert result["action"] == "NEUTRAL"

    def test_unknown_direction_returns_neutral(self):
        """データ不足（unknown）→ NEUTRAL"""
        result = compute_buy_recommendation(
            trend_direction="unknown",
            trend_pct=0.0,
            current_price=0,
            min_price=0,
            avg_price=0,
        )

        assert result["action"] == "NEUTRAL"
        assert "不足" in result["reason"] or "データ" in result["reason"]

    def test_score_range_always_0_to_100(self):
        """スコアは常に0〜100の範囲内"""
        cases = [
            ("rising", 50.0, 150, 100, 120),   # 極端な急騰
            ("falling", -50.0, 50, 30, 100),   # 極端な急落
            ("stable", 0.0, 100, 99, 100),     # 底値圏
        ]
        for args in cases:
            result = compute_buy_recommendation(*args)
            assert 0 <= result["score"] <= 100, (
                f"score={result['score']} が 0〜100 の範囲外: args={args}"
            )


# ============================================================
# API エンドポイントテスト
# ============================================================

@pytest.fixture(scope="module")
def analytics_client():
    """テスト用一時DBを使うFastAPI TestClientを返す。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    os.environ["YUKA_DB_PATH"] = db_path

    import importlib
    import api.services.db as db_mod
    importlib.reload(db_mod)

    from api.main import app
    with TestClient(app) as c:
        yield c

    os.unlink(db_path)


class TestAnalyticsApiNoData:
    """価格データなし時のAPI動作"""

    def test_price_trend_returns_404_when_no_data(self, analytics_client):
        """価格履歴なし → 404"""
        resp = analytics_client.get("/api/analytics/price-trend/NONEXISTENT-PART")
        assert resp.status_code == 404

    def test_buy_recommendation_returns_404_when_no_data(self, analytics_client):
        """価格履歴なし → 404"""
        resp = analytics_client.get("/api/analytics/buy-recommendation/NONEXISTENT-PART")
        assert resp.status_code == 404


class TestAnalyticsApiWithData:
    """価格データあり時のAPI動作"""

    @pytest.fixture(autouse=True)
    def _seed_price_data(self, analytics_client):
        """品番登録 + 価格データを3件シード"""
        # 品番登録
        analytics_client.post(
            "/api/prices/parts",
            json={
                "part_number": "ANALYTICS-TEST-001",
                "description": "アナリティクステスト用部品",
                "category": "テスト",
            },
        )
        # 価格データを手動入力で3件
        for price in [100.0, 105.0, 112.0]:
            analytics_client.post(
                "/api/prices/manual",
                json={
                    "part_number": "ANALYTICS-TEST-001",
                    "description": "アナリティクステスト用部品",
                    "price": price,
                    "source": "manual_test",
                },
            )

    def test_price_trend_returns_200(self, analytics_client):
        """価格データあり → 200 + 正しいフィールド"""
        resp = analytics_client.get("/api/analytics/price-trend/ANALYTICS-TEST-001")
        assert resp.status_code == 200
        data = resp.json()

        assert data["part_number"] == "ANALYTICS-TEST-001"
        assert "trend_direction" in data
        assert data["trend_direction"] in ("rising", "falling", "stable", "unknown")
        assert "trend_pct" in data
        assert "avg_price" in data
        assert "min_price" in data
        assert "max_price" in data
        assert "latest_price" in data
        assert "data_points" in data
        assert data["data_points"] >= 1
        assert "history" in data
        assert isinstance(data["history"], list)

    def test_buy_recommendation_returns_200(self, analytics_client):
        """価格データあり → 200 + 正しいフィールド"""
        resp = analytics_client.get("/api/analytics/buy-recommendation/ANALYTICS-TEST-001")
        assert resp.status_code == 200
        data = resp.json()

        assert data["part_number"] == "ANALYTICS-TEST-001"
        assert data["action"] in ("BUY_NOW", "WAIT", "NEUTRAL")
        assert isinstance(data["reason"], str)
        assert len(data["reason"]) > 0
        assert 0 <= data["score"] <= 100
        assert "current_price" in data
        assert "avg_price" in data
        assert "trend_pct" in data
        assert "trend_direction" in data

    def test_price_trend_rising_with_seeded_data(self, analytics_client):
        """100→105→112 の上昇データ → trend_direction=rising"""
        resp = analytics_client.get("/api/analytics/price-trend/ANALYTICS-TEST-001")
        assert resp.status_code == 200
        data = resp.json()

        # 100→112 で +12% → rising
        assert data["trend_direction"] == "rising"
        assert data["trend_pct"] > 0
