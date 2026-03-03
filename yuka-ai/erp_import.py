"""erp_import.py - ERP直接インポートモジュール（T005b / F-20）

外部ERP/基幹システムへの直接インポート機能。

実装スコープ:
    - REST API経由でのERP連携（mockableインターフェース）
    - 弥生・OBIC・SAP等の汎用アダプター設計
    - インポート結果の記録と確認
    - dry_runモード（実際の送信なしでテスト可能）

環境変数:
    ERP_API_URL      : ERP APIエンドポイントURL
    ERP_API_KEY      : APIキー
    ERP_API_TIMEOUT  : タイムアウト秒数（デフォルト: 30）
    ERP_DRY_RUN      : ドライランモード (true/false)
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

from erp_export import ErpExportRecord, fetch_erp_record


# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

ERP_API_TIMEOUT_DEFAULT = 30


@dataclass
class ErpApiConfig:
    """ERP API接続設定。環境変数から読み込む。"""

    api_url: str = ""
    api_key: str = ""
    timeout: int = ERP_API_TIMEOUT_DEFAULT
    dry_run: bool = True

    @classmethod
    def from_env(cls) -> "ErpApiConfig":
        """環境変数から設定を読み込む。"""
        dry_run_str = os.environ.get("ERP_DRY_RUN", "true").lower()
        return cls(
            api_url=os.environ.get("ERP_API_URL", ""),
            api_key=os.environ.get("ERP_API_KEY", ""),
            timeout=int(os.environ.get("ERP_API_TIMEOUT", str(ERP_API_TIMEOUT_DEFAULT))),
            dry_run=dry_run_str not in ("false", "0", "no"),
        )

    @property
    def is_configured(self) -> bool:
        """API接続に必要な設定が揃っているか確認する。"""
        return bool(self.api_url and self.api_key)


# ---------------------------------------------------------------------------
# インポート結果
# ---------------------------------------------------------------------------

@dataclass
class ErpImportResult:
    """ERP直接インポート結果。

    Attributes:
        success:          インポート成功フラグ
        po_number:        発注番号
        mode:             実行モード ('dry_run' | 'live')
        erp_reference_id: ERPシステム内の参照ID（livモード時）
        payload:          送信したペイロード（デバッグ用）
        response:         ERPからのレスポンス（livモード時）
        imported_at:      インポート日時
        error:            エラーメッセージ（正常時は None）
    """

    success: bool
    po_number: str
    mode: str = "dry_run"
    erp_reference_id: Optional[str] = None
    payload: Optional[dict] = None
    response: Optional[dict] = None
    imported_at: str = ""
    error: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.imported_at:
            self.imported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# ペイロード生成
# ---------------------------------------------------------------------------

def build_erp_payload(record: ErpExportRecord) -> dict:
    """ErpExportRecord を ERP API ペイロードに変換する。

    汎用フォーマット（弥生・OBIC・SAP等への変換は各アダプターで実施）。

    Args:
        record: ERP出力レコード

    Returns:
        dict: APIペイロード
    """
    return {
        "purchase_order": {
            "po_number": record.po_number,
            "supplier_name": record.supplier_name,
            "status": record.status,
            "issue_date": record.issue_date,
            "delivery_date": record.delivery_date,
            "total_amount": record.total_amount,
            "tax_amount": record.tax_amount,
            "grand_total": record.grand_total,
            "exported_at": record.exported_at,
        },
        "items": record.items,
        "metadata": {
            "source": "yuka-ai",
            "version": "1.0.0",
        },
    }


# ---------------------------------------------------------------------------
# インポート実行
# ---------------------------------------------------------------------------

def import_to_erp(
    conn: sqlite3.Connection,
    po_number: str,
    config: Optional[ErpApiConfig] = None,
    dry_run: Optional[bool] = None,
) -> ErpImportResult:
    """発注書をERP/基幹システムへ直接インポートする。

    Args:
        conn:      SQLite接続（発注データ取得用）
        po_number: 発注番号
        config:    ERP API設定（None の場合は環境変数から読み込む）
        dry_run:   ドライランモードの上書き（None の場合は config に従う）

    Returns:
        ErpImportResult: インポート結果
    """
    if config is None:
        config = ErpApiConfig.from_env()

    # dry_run の決定
    effective_dry_run = dry_run if dry_run is not None else config.dry_run

    # 発注データを取得
    record = fetch_erp_record(conn, po_number)
    if record is None:
        return ErpImportResult(
            success=False,
            po_number=po_number,
            mode="dry_run" if effective_dry_run else "live",
            error=f"発注番号 {po_number!r} が見つかりません",
        )

    payload = build_erp_payload(record)

    if effective_dry_run:
        # ドライランモード: 実際の送信はしない
        return ErpImportResult(
            success=True,
            po_number=po_number,
            mode="dry_run",
            erp_reference_id=f"DRY-{po_number}",
            payload=payload,
            response={"status": "dry_run_ok", "message": "ドライランモード: 実際の送信はしていません"},
        )

    # 実モード: HTTP API呼び出し
    if not config.is_configured:
        return ErpImportResult(
            success=False,
            po_number=po_number,
            mode="live",
            payload=payload,
            error="ERP API設定が不完全です。環境変数 ERP_API_URL と ERP_API_KEY を設定してください。",
        )

    return _send_to_erp_api(config, po_number, payload)


def _send_to_erp_api(
    config: ErpApiConfig,
    po_number: str,
    payload: dict,
) -> ErpImportResult:
    """ERP REST APIへリクエストを送信する。

    Args:
        config:    ERP API設定
        po_number: 発注番号
        payload:   送信ペイロード

    Returns:
        ErpImportResult
    """
    try:
        import requests  # noqa: PLC0415

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
            "X-Source": "yuka-ai",
        }

        resp = requests.post(
            f"{config.api_url.rstrip('/')}/purchase-orders",
            json=payload,
            headers=headers,
            timeout=config.timeout,
        )

        if resp.status_code in (200, 201):
            try:
                resp_data = resp.json()
            except Exception:
                resp_data = {"raw": resp.text}

            erp_ref = (
                resp_data.get("id")
                or resp_data.get("reference_id")
                or resp_data.get("po_id")
                or f"ERP-{po_number}"
            )

            return ErpImportResult(
                success=True,
                po_number=po_number,
                mode="live",
                erp_reference_id=str(erp_ref),
                payload=payload,
                response=resp_data,
            )
        else:
            return ErpImportResult(
                success=False,
                po_number=po_number,
                mode="live",
                payload=payload,
                error=f"ERPサーバーエラー: HTTP {resp.status_code} - {resp.text[:200]}",
            )

    except Exception as e:
        return ErpImportResult(
            success=False,
            po_number=po_number,
            mode="live",
            payload=payload,
            error=f"ERP APIリクエストエラー: {e}",
        )


# ---------------------------------------------------------------------------
# インポート履歴管理
# ---------------------------------------------------------------------------

def init_erp_import_log_table(conn: sqlite3.Connection) -> None:
    """erp_import_log テーブルが存在しない場合に作成する。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS erp_import_log (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            po_number          TEXT NOT NULL,
            mode               TEXT NOT NULL,          -- dry_run / live
            success            INTEGER NOT NULL,       -- 0/1
            erp_reference_id   TEXT,
            error              TEXT,
            imported_at        TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.commit()


def record_import_log(conn: sqlite3.Connection, result: ErpImportResult) -> int:
    """インポート結果をログテーブルに記録する。

    Args:
        conn:   SQLite接続
        result: インポート結果

    Returns:
        int: 挿入されたレコードのID
    """
    init_erp_import_log_table(conn)
    cursor = conn.execute(
        "INSERT INTO erp_import_log (po_number, mode, success, erp_reference_id, error) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            result.po_number,
            result.mode,
            1 if result.success else 0,
            result.erp_reference_id,
            result.error,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def list_import_logs(conn: sqlite3.Connection) -> list[dict]:
    """インポート履歴一覧を返す。

    Args:
        conn: SQLite接続

    Returns:
        [{id, po_number, mode, success, erp_reference_id, error, imported_at}]
    """
    init_erp_import_log_table(conn)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, po_number, mode, success, erp_reference_id, error, imported_at "
        "FROM erp_import_log ORDER BY imported_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]
