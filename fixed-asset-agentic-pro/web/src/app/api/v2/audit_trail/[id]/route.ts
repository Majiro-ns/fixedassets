/**
 * GET /api/v2/audit_trail/[id]
 * 根拠: DESIGN_PDF_FIRST_MULTI_AGENT_VER2.md Phase 2 Audit Trail基盤
 *
 * audit_trail_id（trail_xxx）を指定して監査証跡レコードを取得する。
 * classify_pdf レスポンスの audit_trail_id を使って呼び出す。
 */

import { NextRequest, NextResponse } from 'next/server';
import { auditStore } from '@/lib/agents/auditStore';

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
): Promise<NextResponse> {
  const { id } = await params;

  if (!id || typeof id !== 'string' || id.trim() === '') {
    return NextResponse.json({ error: 'Invalid id' }, { status: 400 });
  }

  const record = auditStore.getById(id);
  if (!record) {
    return NextResponse.json({ error: 'Not found' }, { status: 404 });
  }

  return NextResponse.json(record);
}
