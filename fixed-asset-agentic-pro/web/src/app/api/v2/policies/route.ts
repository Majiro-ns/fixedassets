/**
 * GET /api/v2/policies   — ポリシー一覧取得
 * POST /api/v2/policies  — ポリシー新規作成
 * 根拠: cmd_170k_sub2 Phase 3 クライアント別ポリシー管理（F-10）
 */

import { NextRequest, NextResponse } from 'next/server';
import { policyStore } from '@/lib/policyStore';
import type { CreatePolicyInput } from '@/types/policy';

// ─── GET: 一覧 ────────────────────────────────────────────────────────────────

export async function GET(): Promise<NextResponse> {
  const policies = policyStore.listAll();
  return NextResponse.json({ policies });
}

// ─── POST: 作成 ───────────────────────────────────────────────────────────────

export async function POST(req: NextRequest): Promise<NextResponse> {
  let body: CreatePolicyInput;
  try {
    body = (await req.json()) as CreatePolicyInput;
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  if (!body.client_name || typeof body.client_name !== 'string' || body.client_name.trim() === '') {
    return NextResponse.json({ error: 'client_name is required' }, { status: 400 });
  }

  if (
    body.threshold_amount !== undefined &&
    (typeof body.threshold_amount !== 'number' || body.threshold_amount < 0)
  ) {
    return NextResponse.json({ error: 'threshold_amount must be a non-negative number' }, { status: 400 });
  }

  // 重複チェック
  const existing = policyStore.getByClientName(body.client_name.trim());
  if (existing) {
    return NextResponse.json(
      { error: `Policy for client '${body.client_name}' already exists` },
      { status: 409 },
    );
  }

  try {
    const policy = policyStore.create({
      ...body,
      client_name: body.client_name.trim(),
    });
    return NextResponse.json(policy, { status: 201 });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : 'Failed to create policy' },
      { status: 500 },
    );
  }
}
