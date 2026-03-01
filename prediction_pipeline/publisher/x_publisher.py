"""
X（旧Twitter）投稿モジュール
X API v2 を使って競輪予想をポストする。

【認証方式】
  X API v2 でのツイート投稿は OAuth 1.0a User Context が必要。
  標準ライブラリ（hmac / hashlib / base64）で署名を生成するため
  tweepy / requests-oauthlib への依存なし。

【設定読み込み】
  config/settings.yaml の publisher.x_api セクションから認証情報を読み込む。
  実際の値は環境変数で管理すること（"${ENV_VAR}" 形式を自動展開）。

【投稿ルール】
  - tier == "S" のレースのみ投稿する（S評価フィルター）
  - dry_run=True（デフォルト）では API を呼ばずシミュレーション
  - 文字数が CHAR_LIMIT(280)を超える場合は reasoning_short を自動トリム
"""

import base64
import hashlib
import hmac
import logging
import os
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, Optional

import requests
import yaml

logger = logging.getLogger(__name__)

# ─── 定数 ────────────────────────────────────────────────────────────────
_POST_URL  = "https://api.twitter.com/2/tweets"
_CHAR_LIMIT = 280


class XPublisher:
    """X API v2 を使って競輪予想を投稿するクラス。

    S評価のレースのみ投稿対象とする。
    dry_run=True（デフォルト）では実際の API 呼び出しを行わない。

    Example::

        config = yaml.safe_load(Path("config/settings.yaml").read_text())
        pub = XPublisher(config)
        ok = pub.post_prediction(
            tier="S",
            venue="熊本",
            race_info={"race_num": 7, "grade": "特選"},
            buy_tickets={"axis": "3番", "buy": "3-15 3連複"},
            reasoning="捲り系バンク×S級特選×絞れる展開",
            stats={"monthly_recovery": 148.7, "hit_count": 31, "total_count": 131},
        )
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """
        Args:
            config: settings.yaml を yaml.safe_load した辞書。
                    publisher.x_api セクションから認証情報を読み込む。
        """
        pub_cfg  = config.get("publisher", {})
        x_cfg    = pub_cfg.get("x_api", {})
        self._dry_run: bool = pub_cfg.get("dry_run", True)

        # 認証情報（"${ENV_VAR}" 形式の場合は環境変数を展開）
        self._bearer_token         = self._resolve_env(x_cfg.get("bearer_token", ""))
        self._api_key              = self._resolve_env(x_cfg.get("api_key", ""))
        self._api_secret           = self._resolve_env(x_cfg.get("api_secret", ""))
        self._access_token         = self._resolve_env(x_cfg.get("access_token", ""))
        self._access_token_secret  = self._resolve_env(x_cfg.get("access_token_secret", ""))

        # テンプレート読み込み
        template_path = (
            Path(config.get("pipeline", {}).get("config_dir", "config")).parent
            / "publisher" / "templates" / "x_template.txt"
        )
        self._template: str = (
            template_path.read_text(encoding="utf-8")
            if template_path.exists()
            else self._default_template()
        )

    # ────────────────────────────────────────────────────────────────────
    # 公開 API
    # ────────────────────────────────────────────────────────────────────

    def post_prediction(
        self,
        tier: str,
        venue: str,
        race_info: dict[str, Any],
        buy_tickets: dict[str, Any],
        reasoning: str,
        stats: dict[str, Any],
    ) -> bool:
        """競輪予想を X に投稿する。

        S評価のレースのみ実際に投稿する。それ以外は False を返して終了。

        Args:
            tier: 評価ティア。"S" / "A" / "B" / "C"
            venue: 競輪場名（例: "熊本"）
            race_info: レース情報辞書。race_num / grade を含む。
            buy_tickets: 買い目辞書。axis（軸）/ buy（買い目テキスト）を含む。
            reasoning: 予想根拠テキスト（280字制限のため自動トリム）
            stats: 統計辞書。monthly_recovery / hit_count / total_count を含む。

        Returns:
            投稿成功または dry_run シミュレーション成功で True。
            tier が "S" 以外、または投稿失敗で False。
        """
        # S評価のみ投稿
        if tier.upper() != "S":
            logger.debug("tier=%s は投稿対象外（S評価のみ）", tier)
            return False

        text = self._build_post_text(venue, race_info, buy_tickets, reasoning, stats)

        if self._dry_run:
            logger.info("[DRY-RUN] X投稿シミュレーション (%d字):\n%s", len(text), text)
            print(f"[DRY-RUN] X投稿 ({len(text)}字):\n{text}")
            return True

        return self._post_tweet(text)

    # ────────────────────────────────────────────────────────────────────
    # 内部メソッド
    # ────────────────────────────────────────────────────────────────────

    def _build_post_text(
        self,
        venue: str,
        race_info: dict[str, Any],
        buy_tickets: dict[str, Any],
        reasoning: str,
        stats: dict[str, Any],
    ) -> str:
        """テンプレートに変数を埋め込んで投稿テキストを生成する。

        280字を超える場合は reasoning_short を自動トリムする。
        """
        race_num   = race_info.get("race_num", "?")
        grade      = race_info.get("grade", "?")
        axis       = buy_tickets.get("axis", "-")
        buy        = buy_tickets.get("buy", "-")
        m_recovery = stats.get("monthly_recovery", 0.0)
        hit_count  = stats.get("hit_count", 0)
        total      = stats.get("total_count", 0)

        # reasoning を最大 40 字に短縮（280字制限対応）
        reasoning_short = reasoning[:40] + "…" if len(reasoning) > 40 else reasoning

        text = self._template.format(
            venue=venue,
            race_num=race_num,
            grade=grade,
            axis=axis,
            buy_tickets=buy,
            reasoning_short=reasoning_short,
            monthly_recovery=f"{m_recovery:.1f}",
            hit_count=hit_count,
            total_count=total,
        )

        # 文字数オーバー時は reasoning_short をさらに削る
        while len(text) > _CHAR_LIMIT and len(reasoning_short) > 10:
            reasoning_short = reasoning_short[:-5] + "…"
            text = self._template.format(
                venue=venue,
                race_num=race_num,
                grade=grade,
                axis=axis,
                buy_tickets=buy,
                reasoning_short=reasoning_short,
                monthly_recovery=f"{m_recovery:.1f}",
                hit_count=hit_count,
                total_count=total,
            )

        return text.strip()

    def _post_tweet(self, text: str) -> bool:
        """X API v2 POST /2/tweets でツイートを投稿する。

        OAuth 1.0a User Context 署名を標準ライブラリで生成する。

        Args:
            text: 投稿テキスト（280字以内）

        Returns:
            投稿成功で True、失敗で False。
        """
        if not all([self._api_key, self._api_secret,
                    self._access_token, self._access_token_secret]):
            logger.error("X API 認証情報が不足しています。settings.yaml を確認してください。")
            return False

        payload = {"text": text}
        auth_header = self._build_oauth1_header("POST", _POST_URL, {})

        try:
            resp = requests.post(
                _POST_URL,
                json=payload,
                headers={
                    "Authorization": auth_header,
                    "Content-Type": "application/json",
                },
                timeout=15,
            )
            if resp.status_code in (200, 201):
                tweet_id = resp.json().get("data", {}).get("id", "?")
                logger.info("X 投稿成功: tweet_id=%s", tweet_id)
                return True
            else:
                logger.error("X 投稿失敗: %d %s", resp.status_code, resp.text)
                return False
        except requests.RequestException as exc:
            logger.error("X API リクエストエラー: %s", exc)
            return False

    def _build_oauth1_header(
        self, method: str, url: str, params: dict[str, str]
    ) -> str:
        """OAuth 1.0a 署名ヘッダーを標準ライブラリで生成する。

        tweepy / requests-oauthlib への依存なし。
        HMAC-SHA1 署名方式を使用する。

        Args:
            method: HTTP メソッド（"POST"）
            url: リクエスト URL
            params: クエリパラメータ辞書

        Returns:
            "OAuth ..." 形式の Authorization ヘッダー文字列
        """
        nonce     = uuid.uuid4().hex
        timestamp = str(int(time.time()))

        oauth_params: dict[str, str] = {
            "oauth_consumer_key":     self._api_key,
            "oauth_nonce":            nonce,
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp":        timestamp,
            "oauth_token":            self._access_token,
            "oauth_version":          "1.0",
        }

        # ベース文字列構築
        all_params = {**params, **oauth_params}
        sorted_params = sorted(
            (urllib.parse.quote(k, safe=""), urllib.parse.quote(str(v), safe=""))
            for k, v in all_params.items()
        )
        param_str = "&".join(f"{k}={v}" for k, v in sorted_params)
        base_str  = "&".join([
            method.upper(),
            urllib.parse.quote(url, safe=""),
            urllib.parse.quote(param_str, safe=""),
        ])

        # 署名キー & HMAC-SHA1 署名
        signing_key = (
            urllib.parse.quote(self._api_secret, safe="")
            + "&"
            + urllib.parse.quote(self._access_token_secret, safe="")
        )
        signature = base64.b64encode(
            hmac.new(
                signing_key.encode("utf-8"),
                base_str.encode("utf-8"),
                hashlib.sha1,
            ).digest()
        ).decode("utf-8")

        oauth_params["oauth_signature"] = signature
        header_parts = ", ".join(
            f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
            for k, v in sorted(oauth_params.items())
        )
        return f"OAuth {header_parts}"

    @staticmethod
    def _resolve_env(value: str) -> str:
        """"${ENV_VAR}" 形式の文字列を環境変数の値に展開する。

        環境変数が未設定の場合は空文字列を返す。
        """
        if value.startswith("${") and value.endswith("}"):
            env_name = value[2:-1]
            return os.environ.get(env_name, "")
        return value

    @staticmethod
    def _default_template() -> str:
        """テンプレートファイルが見つからない場合のフォールバックテンプレート。"""
        return (
            "🏁【{venue} {race_num}R / {grade}】S評価\n"
            "🎯 軸:{axis} / 買い目:{buy_tickets}\n"
            "📊 {reasoning_short}\n"
            "📈 月次回収率{monthly_recovery}% 的中{hit_count}/{total_count}件\n"
            "#競輪予想 #{venue}競輪"
        )


# ─── __main__ dry-run テスト ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    config = {
        "publisher": {"dry_run": True, "x_api": {}},
        "pipeline":  {"config_dir": "config"},
    }
    pub = XPublisher(config)

    # S評価: 投稿される
    ok = pub.post_prediction(
        tier="S",
        venue="熊本",
        race_info={"race_num": 7, "grade": "特選"},
        buy_tickets={"axis": "3番", "buy": "3-15 3連複 ながし"},
        reasoning="捲り系バンク×S級特選×絞れる展開。3番の機動力が抜群。",
        stats={"monthly_recovery": 148.7, "hit_count": 31, "total_count": 131},
    )
    print(f"S評価投稿: {ok}")

    # A評価: 投稿されない
    ok2 = pub.post_prediction(
        tier="A",
        venue="熊本",
        race_info={"race_num": 8, "grade": "二次予選"},
        buy_tickets={"axis": "1番", "buy": "1-234"},
        reasoning="標準型",
        stats={"monthly_recovery": 148.7, "hit_count": 31, "total_count": 131},
    )
    print(f"A評価投稿（False expected）: {ok2}")
