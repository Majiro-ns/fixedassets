import { NextRequest, NextResponse } from 'next/server';
import type { DepreciationRequest, DepreciationResponse } from '@/types/depreciation';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export async function POST(req: NextRequest): Promise<NextResponse> {
  let body: DepreciationRequest;
  try {
    body = (await req.json()) as DepreciationRequest;
  } catch {
    return NextResponse.json(
      { error: 'リクエストのパースに失敗しました' },
      { status: 400 },
    );
  }

  try {
    const upstream = await fetch(`${API_BASE}/calculate_depreciation`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    if (!upstream.ok) {
      const text = await upstream.text();
      return NextResponse.json(
        { error: `バックエンドエラー ${upstream.status}: ${text}` },
        { status: upstream.status },
      );
    }

    const data = (await upstream.json()) as DepreciationResponse;
    return NextResponse.json(data);
  } catch (err) {
    const message = err instanceof Error ? err.message : '不明なエラー';
    return NextResponse.json(
      { error: `バックエンド接続エラー: ${message}` },
      { status: 502 },
    );
  }
}
