"""ERP router - purchase order export and import for ERP integration."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from api.models.schemas import (
    ErpExportLogItem,
    ErpImportRequest,
    ErpImportResponse,
    ErpImportLogItem,
)
from api.services.db import get_connection

router = APIRouter(prefix="/api/erp", tags=["erp"])


@router.get("/export/{po_number}")
def export_erp(po_number: str, fmt: str = Query("csv", pattern="^(csv|json)$")):
    """発注書をERP向けCSV/JSONでエクスポートする。

    - fmt=csv (デフォルト): CSV形式でダウンロード
    - fmt=json: JSON形式でダウンロード
    """
    try:
        conn = get_connection()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB接続エラー: {e}")
    try:
        from erp_export import export_po
        success, content = export_po(conn, po_number, fmt)
        if not success:
            raise HTTPException(status_code=404, detail=content)
        media_type = "text/csv; charset=utf-8" if fmt == "csv" else "application/json"
        return Response(
            content=content.encode("utf-8"),
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{po_number}.{fmt}"',
            },
        )
    finally:
        conn.close()


@router.get("/logs", response_model=list[ErpExportLogItem])
async def list_erp_logs():
    """ERP向けエクスポート履歴一覧を返す。"""
    try:
        conn = get_connection()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB接続エラー: {e}")
    try:
        from erp_export import list_export_logs, init_erp_log_table
        init_erp_log_table(conn)
        logs = list_export_logs(conn)
        return [ErpExportLogItem(**log) for log in logs]
    finally:
        conn.close()


@router.post("/import", response_model=ErpImportResponse)
async def import_to_erp_system(req: ErpImportRequest):
    """発注書をERP/基幹システムへ直接インポートする。

    - dry_run=true (デフォルト): 実際の送信をせずペイロードを検証
    - dry_run=false: 環境変数 ERP_API_URL/ERP_API_KEY で実送信
    """
    try:
        conn = get_connection()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB接続エラー: {e}")
    try:
        from erp_import import import_to_erp, record_import_log, ErpApiConfig

        config = ErpApiConfig.from_env()
        result = import_to_erp(
            conn=conn,
            po_number=req.po_number,
            config=config,
            dry_run=req.dry_run,
        )

        if not result.success and "見つかりません" in (result.error or ""):
            raise HTTPException(status_code=404, detail=result.error)

        # ログ記録
        record_import_log(conn, result)

        return ErpImportResponse(
            success=result.success,
            po_number=result.po_number,
            mode=result.mode,
            erp_reference_id=result.erp_reference_id,
            imported_at=result.imported_at,
            error=result.error,
        )
    finally:
        conn.close()


@router.get("/import/logs", response_model=list[ErpImportLogItem])
async def list_erp_import_logs():
    """ERP直接インポート履歴一覧を返す。"""
    try:
        conn = get_connection()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB接続エラー: {e}")
    try:
        from erp_import import list_import_logs
        logs = list_import_logs(conn)
        return [
            ErpImportLogItem(
                id=log["id"],
                po_number=log["po_number"],
                mode=log["mode"],
                success=bool(log["success"]),
                erp_reference_id=log.get("erp_reference_id"),
                error=log.get("error"),
                imported_at=log["imported_at"],
            )
            for log in logs
        ]
    finally:
        conn.close()
