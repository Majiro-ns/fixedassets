/**
 * GET /api/v2/audit_trail
 *
 * T013: 監査証跡一覧取得エンドポイント (cmd_182k_A4b)
 * auditStore から全件（または limit 件）の AuditRecord を返す。
 *
 * Query Parameters:
 *   limit?: number  最大取得件数（正の整数）。省略時は全件取得。
 *
 * Response:
 *   200: AuditRecord[]  timestamp 降順
 *   400: { error: 'Invalid limit parameter' }  limit が不正値
 *   500: { error: string }  DB 例外等
 *
 * 注意:
 *   ?asset_id による絞り込みは auditStore が getByAssetId を持たないため未対応。
 *   将来的に auditStore に getByAssetId を追加して対応すること。
 *
 * (T013 / cmd_182k_A4b)
 */

import { NextRequest, NextResponse } from 'next/server';
import { auditStore } from '@/lib/agents/auditStore';

export async function GET(req: NextRequest): Promise<NextResponse> {
  // 1. limit クエリパラメータの解析・バリデーション
  const limitParam = req.nextUrl.searchParams.get('limit');
  let limit: number | undefined;

  if (limitParam !== null) {
    limit = parseInt(limitParam, 10);
    if (isNaN(limit) || limit <= 0) {
      return NextResponse.json(
        { error: 'Invalid limit parameter' },
        { status: 400 },
      );
    }
  }

  // 2. ストアから取得して返す
  try {
    const records = auditStore.list(limit);
    return NextResponse.json(records);
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Internal server error';
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
