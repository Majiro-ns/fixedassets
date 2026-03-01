"""
note.com 投稿モジュール
note の非公式 REST API を使って日次・週次レポート記事を投稿する。

【認証方式】
  note.com の非公式 API: https://note.com/api/v3/
  セッショントークン（Cookie: note_gk_session）による認証。
  認証情報は config/settings.yaml の publisher.note セクションから読み込む。

【投稿フロー】
  1. POST /api/v3/text_notes でドラフト記事を作成
  2. PUT /api/v3/text_notes/{note_id}/publish で公開
  マガジン ID が設定されている場合は自動でマガジンに追加する。

【dry_run モード（デフォルト True）】
  dry_run=True の場合は API を呼ばず、生成した Markdown を返すのみ。

【注意事項】
  note.com の API は公式公開されていない。
  利用規約を確認のうえ使用すること。
  過剰なリクエストは送らないこと（1日1〜2件程度）。
"""

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests
import yaml

logger = logging.getLogger(__name__)

# ─── 定数 ────────────────────────────────────────────────────────────────
_BASE_URL        = "https://note.com/api/v3"
_RATE_LIMIT_SEC  = 5.0  # 投稿間隔（秒）


class NotePublisher:
    """note.com に日次・週次レポート記事を投稿するクラス。

    dry_run=True（デフォルト）では実際の投稿を行わず、
    生成した Markdown をログ出力するのみ。

    Example::

        config = yaml.safe_load(Path("config/settings.yaml").read_text())
        pub = NotePublisher(config)

        # 日次レポート投稿
        pub.post_daily(
            date="2026-02-22",
            predictions_by_tier={"S": [...], "A": [...], "B": [...]},
            stats={"monthly_recovery": 148.7, "hit_count": 31},
        )

        # 週次レポート投稿
        pub.post_weekly(report_md="# 週次レポート\\n...")
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """
        Args:
            config: settings.yaml を yaml.safe_load した辞書。
                    publisher.note セクションから認証情報を読み込む。
        """
        pub_cfg  = config.get("publisher", {})
        note_cfg = pub_cfg.get("note", {})
        self._dry_run: bool = pub_cfg.get("dry_run", True)

        # 認証情報（"${ENV_VAR}" 形式を自動展開）
        self._session_token = self._resolve_env(note_cfg.get("session_token", ""))
        self._user_id       = self._resolve_env(note_cfg.get("user_id", ""))
        self._magazine_id   = self._resolve_env(note_cfg.get("magazine_id", ""))

        # テンプレートディレクトリ
        tmpl_dir = (
            Path(config.get("pipeline", {}).get("config_dir", "config")).parent
            / "publisher" / "templates"
        )
        self._daily_template  = self._load_template(tmpl_dir / "note_daily_template.md")
        self._weekly_template = self._load_template(tmpl_dir / "note_weekly_template.md")

    # ────────────────────────────────────────────────────────────────────
    # 公開 API
    # ────────────────────────────────────────────────────────────────────

    def post_daily(
        self,
        date: str,
        predictions_by_tier: dict[str, list[dict[str, Any]]],
        stats: dict[str, Any],
    ) -> bool:
        """日次予想レポートを note に投稿する。

        Args:
            date: 対象日付（YYYY-MM-DD 形式、例: "2026-02-22"）
            predictions_by_tier: ティア別予想リスト。
                キー: "S" / "A" / "B" / "C"。
                値: 各ティアの予想辞書リスト（venue/race_num/buy_tickets/reasoning 等を含む）
            stats: 集計統計辞書。以下のキーを参照する:
                - total_investment, total_payout, net_profit, daily_recovery
                - monthly_recovery, monthly_profit, monthly_hit_rate

        Returns:
            投稿成功または dry_run で True。投稿失敗で False。
        """
        md = self._render_daily(date, predictions_by_tier, stats)
        title = f"{date} 競輪予想 日次レポート【AI予想パイプライン】"

        if self._dry_run:
            logger.info("[DRY-RUN] note日次投稿シミュレーション: %s\n%s", title, md[:300])
            print(f"[DRY-RUN] note日次投稿: {title} ({len(md)}字)")
            return True

        return self._publish_note(title, md)

    def post_weekly(self, report_md: str) -> bool:
        """週次レポート記事を note に投稿する。

        Args:
            report_md: 投稿する Markdown 本文。呼び出し元が
                       note_weekly_template.md を元に生成して渡す。
                       空の場合は投稿をスキップする。

        Returns:
            投稿成功または dry_run で True。投稿失敗で False。
        """
        if not report_md.strip():
            logger.warning("週次レポート本文が空です。投稿をスキップします。")
            return False

        # タイトルを本文先頭行（# ...）から抽出
        title = self._extract_title(report_md)

        if self._dry_run:
            logger.info("[DRY-RUN] note週次投稿シミュレーション: %s\n%s", title, report_md[:300])
            print(f"[DRY-RUN] note週次投稿: {title} ({len(report_md)}字)")
            return True

        return self._publish_note(title, report_md)

    def render_weekly(
        self,
        week_label: str,
        week_start: str,
        week_end: str,
        weekly_stats: dict[str, Any],
    ) -> str:
        """週次レポートテンプレートに統計データを埋め込んで Markdown を生成する。

        Args:
            week_label: 週ラベル（例: "2026年第8週"）
            week_start: 週開始日（YYYY-MM-DD）
            week_end:   週終了日（YYYY-MM-DD）
            weekly_stats: 週次統計辞書。テンプレートの全変数に対応するキーを含む。

        Returns:
            テンプレートに変数を埋め込んだ Markdown 文字列
        """
        return self._weekly_template.format(
            week_label=week_label,
            week_start=week_start,
            week_end=week_end,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            **weekly_stats,
        )

    # ────────────────────────────────────────────────────────────────────
    # 内部: Markdown 生成
    # ────────────────────────────────────────────────────────────────────

    def _render_daily(
        self,
        date: str,
        predictions_by_tier: dict[str, list[dict[str, Any]]],
        stats: dict[str, Any],
    ) -> str:
        """日次テンプレートに予想データを埋め込んで Markdown を生成する。"""
        s_preds = predictions_by_tier.get("S", [])
        a_preds = predictions_by_tier.get("A", [])
        b_preds = predictions_by_tier.get("B", [])
        c_preds = predictions_by_tier.get("C", [])

        return self._daily_template.format(
            date=date,
            total_races=sum(
                len(v) for v in predictions_by_tier.values()
            ),
            s_count=len(s_preds),
            a_count=len(a_preds),
            b_count=len(b_preds),
            c_count=len(c_preds),
            s_predictions=self._format_predictions(s_preds),
            a_predictions=self._format_predictions(a_preds),
            b_predictions=self._format_predictions(b_preds),
            total_investment=stats.get("total_investment", "-"),
            total_payout=stats.get("total_payout", "-"),
            net_profit=stats.get("net_profit", "-"),
            daily_recovery=stats.get("daily_recovery", "-"),
            monthly_recovery=stats.get("monthly_recovery", "-"),
            monthly_profit=stats.get("monthly_profit", "-"),
            monthly_hit_rate=stats.get("monthly_hit_rate", "-"),
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        )

    @staticmethod
    def _format_predictions(preds: list[dict[str, Any]]) -> str:
        """予想リストを Markdown テーブル形式にフォーマットする。"""
        if not preds:
            return "（対象レースなし）"

        lines = [
            "| 競輪場 | R | グレード | 買い目 | 根拠 |",
            "|--------|---|----------|--------|------|",
        ]
        for p in preds:
            venue    = p.get("venue", "-")
            race_num = p.get("race_num", "-")
            grade    = p.get("grade", "-")
            buy      = p.get("buy_tickets", {})
            buy_str  = buy.get("buy", "-") if isinstance(buy, dict) else str(buy)
            reason   = p.get("reasoning", "-")[:60] + "…" if len(p.get("reasoning", "")) > 60 else p.get("reasoning", "-")
            lines.append(f"| {venue} | {race_num} | {grade} | {buy_str} | {reason} |")

        return "\n".join(lines)

    # ────────────────────────────────────────────────────────────────────
    # 内部: note API 呼び出し
    # ────────────────────────────────────────────────────────────────────

    def _publish_note(self, title: str, body_md: str) -> bool:
        """note API を使って記事をドラフト作成→公開する。

        Args:
            title: 記事タイトル
            body_md: 記事本文（Markdown）

        Returns:
            公開成功で True、失敗で False。
        """
        if not self._session_token:
            logger.error("NOTE_SESSION_TOKEN が未設定です。settings.yaml を確認してください。")
            return False

        headers = {
            "Cookie": f"note_gk_session={self._session_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Referer": "https://note.com",
            "User-Agent": "PredictionPipeline/1.0",
        }

        # ステップ1: ドラフト記事作成
        draft_payload: dict[str, Any] = {
            "text_note": {
                "title":   title,
                "body":    body_md,
                "status":  "draft",
            }
        }
        if self._magazine_id:
            draft_payload["text_note"]["magazine_id"] = self._magazine_id

        try:
            time.sleep(_RATE_LIMIT_SEC)
            resp = requests.post(
                f"{_BASE_URL}/text_notes",
                json=draft_payload,
                headers=headers,
                timeout=20,
            )
            if resp.status_code not in (200, 201):
                logger.error("note ドラフト作成失敗: %d %s", resp.status_code, resp.text[:200])
                return False

            note_id = resp.json().get("data", {}).get("id")
            if not note_id:
                logger.error("note ドラフト作成: note_id が取得できませんでした")
                return False

            logger.info("note ドラフト作成: note_id=%s", note_id)

            # ステップ2: 公開
            time.sleep(_RATE_LIMIT_SEC)
            pub_resp = requests.put(
                f"{_BASE_URL}/text_notes/{note_id}/publish",
                json={"status": "published"},
                headers=headers,
                timeout=20,
            )
            if pub_resp.status_code in (200, 201):
                logger.info("note 公開成功: note_id=%s", note_id)
                return True
            else:
                logger.error("note 公開失敗: %d %s", pub_resp.status_code, pub_resp.text[:200])
                return False

        except requests.RequestException as exc:
            logger.error("note API リクエストエラー: %s", exc)
            return False

    # ────────────────────────────────────────────────────────────────────
    # 補助メソッド
    # ────────────────────────────────────────────────────────────────────

    @staticmethod
    def _load_template(path: Path) -> str:
        """テンプレートファイルを読み込む。存在しない場合は空文字を返す。"""
        if path.exists():
            return path.read_text(encoding="utf-8")
        logger.warning("テンプレートファイルが見つかりません: %s", path)
        return "{date} レポート\n{s_predictions}"

    @staticmethod
    def _extract_title(md: str) -> str:
        """Markdown 本文の先頭 `# ...` 行からタイトルを抽出する。"""
        for line in md.splitlines():
            stripped = line.lstrip("#").strip()
            if stripped:
                return stripped
        return "競輪予想レポート"

    @staticmethod
    def _resolve_env(value: str) -> str:
        """"${ENV_VAR}" 形式の文字列を環境変数の値に展開する。"""
        if value.startswith("${") and value.endswith("}"):
            env_name = value[2:-1]
            return os.environ.get(env_name, "")
        return value


# ─── __main__ dry-run テスト ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    config = {
        "publisher": {"dry_run": True, "note": {}},
        "pipeline":  {"config_dir": "config"},
    }
    pub = NotePublisher(config)

    # 日次レポートテスト
    ok = pub.post_daily(
        date="2026-02-22",
        predictions_by_tier={
            "S": [
                {"venue": "熊本", "race_num": 7, "grade": "特選",
                 "buy_tickets": {"buy": "3-15 3連複"}, "reasoning": "捲り系バンク×S級特選"},
            ],
            "A": [],
            "B": [],
            "C": [],
        },
        stats={
            "total_investment": 12000,
            "total_payout": 0,
            "net_profit": -12000,
            "daily_recovery": 0,
            "monthly_recovery": 148.7,
            "monthly_profit": 635580,
            "monthly_hit_rate": 24.4,
        },
    )
    print(f"note日次投稿 dry-run: {ok}")

    # 週次レポートテスト
    ok2 = pub.post_weekly("# 2026年第8週 競輪予想 週次レポート\n\nテスト本文")
    print(f"note週次投稿 dry-run: {ok2}")
