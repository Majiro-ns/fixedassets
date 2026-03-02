/**
 * GET    /api/v2/policies/[id] — ポリシー詳細取得
 * PUT    /api/v2/policies/[id] — ポリシー更新
 * DELETE /api/v2/policies/[id] — ポリシー削除
 * 根拠: cmd_170k_sub2 Phase 3 クライアント別ポリシー管理（F-10）
 */

import { NextRequest, NextResponse } from 'next/server';
import { policyStore } from '@/lib/policyStore';
import type { UpdatePolicyInput } from '@/types/policy';

type Params = { params: Promise<{ id: string }> };

function parseId(raw: string): number | null {
  const n = Number(raw);
  return Number.isInteger(n) && n > 0 ? n : null;
}

// ─── GET: 詳細 ────────────────────────────────────────────────────────────────

export async function GET(_req: NextRequest, { params }: Params): Promise<NextResponse> {
  const { id: rawId } = await params;
  const id = parseId(rawId);
  if (id === null) return NextResponse.json({ error: 'Invalid id' }, { status: 400 });

  const policy = policyStore.getById(id);
  if (!policy) return NextResponse.json({ error: 'Not found' }, { status: 404 });
  return NextResponse.json(policy);
}

// ─── PUT: 更新 ────────────────────────────────────────────────────────────────

export async function PUT(req: NextRequest, { params }: Params): Promise<NextResponse> {
  const { id: rawId } = await params;
  const id = parseId(rawId);
  if (id === null) return NextResponse.json({ error: 'Invalid id' }, { status: 400 });

  let body: UpdatePolicyInput;
  try {
    body = (await req.json()) as UpdatePolicyInput;
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  if (
    body.threshold_amount !== undefined &&
    (typeof body.threshold_amount !== 'number' || body.threshold_amount < 0)
  ) {
    return NextResponse.json({ error: 'threshold_amount must be a non-negative number' }, { status: 400 });
  }

  const updated = policyStore.update(id, body);
  if (!updated) return NextResponse.json({ error: 'Not found' }, { status: 404 });
  return NextResponse.json(updated);
}

// ─── DELETE: 削除 ─────────────────────────────────────────────────────────────

export async function DELETE(_req: NextRequest, { params }: Params): Promise<NextResponse> {
  const { id: rawId } = await params;
  const id = parseId(rawId);
  if (id === null) return NextResponse.json({ error: 'Invalid id' }, { status: 400 });

  const deleted = policyStore.delete(id);
  if (!deleted) return NextResponse.json({ error: 'Not found' }, { status: 404 });
  return NextResponse.json({ success: true });
}
