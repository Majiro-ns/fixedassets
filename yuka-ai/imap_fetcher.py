"""imap_fetcher.py - IMAP自動取得モジュール（T005b / F-18）

メールボックスから請求書・発注書メールを自動取得する。

実装スコープ:
    - 環境変数からIMAP設定を読み込み
    - mockモード: 実際の接続なしでテスト可能
    - 実モード: imaplib で IMAP接続
    - 件名・送信元フィルタリング
    - EmailData 形式で返却（email_parser.py との統合）

環境変数:
    IMAP_HOST     : IMAPサーバーホスト（例: imap.gmail.com）
    IMAP_PORT     : IMAPポート（デフォルト: 993）
    IMAP_USER     : ユーザー名（メールアドレス）
    IMAP_PASSWORD : パスワード / アプリパスワード
    IMAP_MAILBOX  : メールボックス名（デフォルト: INBOX）
    IMAP_USE_SSL  : SSL使用 (true/false, デフォルト: true)
"""

from __future__ import annotations

import imaplib
import os
from dataclasses import dataclass, field
from typing import Optional

from email_parser import EmailData, parse_email_text, _parse_eml_bytes


# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

IMAP_HOST_DEFAULT = "imap.gmail.com"
IMAP_PORT_DEFAULT = 993


@dataclass
class ImapConfig:
    """IMAP接続設定。環境変数から読み込む。"""

    host: str = IMAP_HOST_DEFAULT
    port: int = IMAP_PORT_DEFAULT
    user: str = ""
    password: str = ""
    mailbox: str = "INBOX"
    use_ssl: bool = True

    @classmethod
    def from_env(cls) -> "ImapConfig":
        """環境変数から設定を読み込む。"""
        use_ssl_str = os.environ.get("IMAP_USE_SSL", "true").lower()
        return cls(
            host=os.environ.get("IMAP_HOST", IMAP_HOST_DEFAULT),
            port=int(os.environ.get("IMAP_PORT", str(IMAP_PORT_DEFAULT))),
            user=os.environ.get("IMAP_USER", ""),
            password=os.environ.get("IMAP_PASSWORD", ""),
            mailbox=os.environ.get("IMAP_MAILBOX", "INBOX"),
            use_ssl=use_ssl_str not in ("false", "0", "no"),
        )

    @property
    def is_configured(self) -> bool:
        """接続に必要な設定が揃っているか確認する。"""
        return bool(self.host and self.user and self.password)


# ---------------------------------------------------------------------------
# フェッチ結果
# ---------------------------------------------------------------------------

@dataclass
class ImapFetchResult:
    """IMAP取得結果。

    Attributes:
        emails:    取得したメールのリスト (EmailData)
        fetched_count: 取得件数
        mode:      実行モード ('mock' | 'live')
        error:     エラーメッセージ（正常時は None）
    """

    emails: list[EmailData] = field(default_factory=list)
    fetched_count: int = 0
    mode: str = "mock"
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# モックデータ
# ---------------------------------------------------------------------------

_MOCK_EMAILS = [
    {
        "subject": "【発注確認】PO-2026-001 について",
        "from": "supplier@example.com",
        "body": (
            "発注番号: PO-2026-001\n"
            "品番: SFJ6-30 数量: 100\n"
            "納品予定日: 2026年03月20日\n"
        ),
    },
    {
        "subject": "請求書 No.INV-2026-042 送付のお知らせ",
        "from": "billing@parts-vendor.co.jp",
        "body": (
            "請求書番号: INV-2026-042\n"
            "品番: MT-GLOVE-L 数量: 50\n"
            "合計金額: 55,000円（税込）\n"
        ),
    },
]


def _build_mock_email_data(raw: dict) -> EmailData:
    """モックデータから EmailData を生成する。"""
    text = f"Subject: {raw['subject']}\nFrom: {raw['from']}\n\n{raw['body']}"
    data = parse_email_text(text, source="mock_imap")
    return data


# ---------------------------------------------------------------------------
# IMAP取得本体
# ---------------------------------------------------------------------------

def fetch_invoice_emails(
    config: Optional[ImapConfig] = None,
    limit: int = 10,
    subject_filter: Optional[str] = None,
    dry_run: bool = False,
) -> ImapFetchResult:
    """メールボックスから請求書・発注確認メールを取得する。

    Args:
        config:         IMAP設定（None の場合は環境変数から読み込む）
        limit:          最大取得件数（デフォルト: 10）
        subject_filter: 件名フィルター文字列（部分一致、None の場合はフィルタなし）
        dry_run:        True の場合は実接続せずモックデータを返す

    Returns:
        ImapFetchResult: 取得結果
    """
    if config is None:
        config = ImapConfig.from_env()

    # dry_run モードまたは設定未完了の場合はモックデータを返す
    if dry_run or not config.is_configured:
        mock_data = [_build_mock_email_data(m) for m in _MOCK_EMAILS]

        # subject_filter 適用
        if subject_filter:
            mock_data = [
                e for e in mock_data
                if subject_filter.lower() in e.subject.lower()
            ]

        # limit 適用
        mock_data = mock_data[:limit]

        return ImapFetchResult(
            emails=mock_data,
            fetched_count=len(mock_data),
            mode="mock",
            error=None,
        )

    # 実IMAP接続
    try:
        return _fetch_live(config, limit, subject_filter)
    except Exception as e:
        return ImapFetchResult(
            emails=[],
            fetched_count=0,
            mode="live",
            error=f"IMAP接続エラー: {e}",
        )


def _fetch_live(
    config: ImapConfig,
    limit: int,
    subject_filter: Optional[str],
) -> ImapFetchResult:
    """実IMAP接続でメールを取得する。"""
    emails: list[EmailData] = []

    if config.use_ssl:
        conn = imaplib.IMAP4_SSL(config.host, config.port)
    else:
        conn = imaplib.IMAP4(config.host, config.port)

    try:
        conn.login(config.user, config.password)
        conn.select(config.mailbox, readonly=True)

        # 件名フィルター付き検索
        if subject_filter:
            search_criteria = f'SUBJECT "{subject_filter}"'
            typ, msg_ids = conn.search(None, search_criteria)
        else:
            typ, msg_ids = conn.search(None, "ALL")

        if typ != "OK":
            return ImapFetchResult(
                emails=[],
                fetched_count=0,
                mode="live",
                error=f"メール検索失敗: {typ}",
            )

        id_list = msg_ids[0].split()
        # 最新のものから取得（リバース）
        id_list = list(reversed(id_list))[:limit]

        for msg_id in id_list:
            typ, msg_data = conn.fetch(msg_id, "(RFC822)")
            if typ != "OK":
                continue
            raw_bytes = msg_data[0][1]
            if not isinstance(raw_bytes, bytes):
                continue
            subject, sender, body = _parse_eml_bytes(raw_bytes)
            from email_parser import _extract_order_number, _extract_delivery_date, _extract_items
            full_text = subject + " " + body
            email_data = EmailData(
                subject=subject,
                sender=sender,
                body=body,
                order_number=_extract_order_number(full_text),
                delivery_date=_extract_delivery_date(full_text),
                extracted_items=_extract_items(body),
                source="imap",
            )
            emails.append(email_data)

    finally:
        try:
            conn.logout()
        except Exception:
            pass

    return ImapFetchResult(
        emails=emails,
        fetched_count=len(emails),
        mode="live",
        error=None,
    )
