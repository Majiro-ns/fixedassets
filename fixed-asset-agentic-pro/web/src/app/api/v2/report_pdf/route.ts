/**
 * POST /api/v2/report_pdf
 *
 * F-12: 証跡レポート PDF 生成プロキシ
 * フロントエンドからの POST を Python バックエンド /report/pdf へ転送し、
 * application/pdf レスポンスをそのままクライアントに返す。
 *
 * Request body (JSON):
 *   items         ReportLineItem[]  明細リスト
 *   summary       ReportSummary     集計情報
 *   source_filename? string         元 PDF ファイル名（省略可）
 *   audit_trail_id? string          監査証跡 ID（省略可）
 *
 * Response:
 *   Content-Type: application/pdf
 *   Content-Disposition: attachment; filename="fixed_asset_report_YYYYMMDD.pdf"
 *
 * (F-12 / cmd_149k_sub7)
 */

import { NextRequest, NextResponse } from 'next/server';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
const TIMEOUT_MS = 15_000;

export async function POST(req: NextRequest): Promise<NextResponse> {
  // 1. リクエスト解析
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  // 2. バックエンド呼び出し（タイムアウト付き）
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  let backendRes: Response;
  try {
    backendRes = await fetch(`${API_BASE}/report/pdf`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (err) {
    clearTimeout(timer);
    const msg = err instanceof Error ? err.message : 'Backend unreachable';
    return NextResponse.json({ error: msg }, { status: 503 });
  } finally {
    clearTimeout(timer);
  }

  if (!backendRes.ok) {
    const text = await backendRes.text();
    return NextResponse.json({ error: `Backend error: ${text}` }, { status: backendRes.status });
  }

  // 3. PDF バイナリをそのまま返す
  const pdfBytes = await backendRes.arrayBuffer();
  const today = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  const filename = `fixed_asset_report_${today}.pdf`;

  return new NextResponse(pdfBytes, {
    status: 200,
    headers: {
      'Content-Type': 'application/pdf',
      'Content-Disposition': `attachment; filename="${filename}"`,
    },
  });
}
