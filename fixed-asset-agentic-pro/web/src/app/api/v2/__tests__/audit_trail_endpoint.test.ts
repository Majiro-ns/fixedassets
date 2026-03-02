/**
 * GET /api/v2/audit_trail/[id] ルートハンドラーテスト
 * 根拠: DESIGN_PDF_FIRST_MULTI_AGENT_VER2.md Phase 2 Audit Trail基盤
 *
 * テスト戦略:
 *   - GET ハンドラーを直接 import して呼び出す（Next.js Route Handler 単体テスト）
 *   - auditStore を beforeEach でリセットし、テストデータをセットアップ
 *   - 正常系 / 404 / 不正ID の 3 パターンを検証
 *
 * CHECK-9: 全テストに根拠コメントを記載。
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { NextRequest } from 'next/server';
import { GET } from '../audit_trail/[id]/route';
import * as auditStoreModule from '@/lib/agents/auditStore';
import type { AuditRecord } from '@/types/audit_trail';

// ─── テストデータ ───────────────────────────────────────────────────────────

function makeRecord(overrides?: Partial<AuditRecord>): AuditRecord {
  return {
    audit_trail_id: 'trail_test001',
    request_id: 'req_uuid_test001',
    timestamp: '2026-03-02T10:00:00.000Z',
    pdf_filename: 'document.pdf',
    line_items_count: 2,
    tax_verdict: 'CAPITAL',
    practice_verdict: 'CAPITAL',
    final_verdict: 'CAPITAL_LIKE',
    confidence: 0.95,
    account_category: '器具備品',
    useful_life: 4,
    elapsed_ms: 1200,
    model_used: 'claude-haiku-4-5',
    ...overrides,
  };
}

// ─── ハンドラー直接呼び出しユーティリティ ──────────────────────────────────

async function callGet(id: string) {
  const req = new NextRequest(`http://localhost/api/v2/audit_trail/${id}`);
  return GET(req, { params: Promise.resolve({ id }) });
}

// ─── テスト ─────────────────────────────────────────────────────────────────

describe('GET /api/v2/audit_trail/[id]', () => {
  beforeEach(() => {
    // グローバルシングルトンをリセット
    auditStoreModule.auditStore.clear();
  });

  // 正常系 ─────────────────────────────────────────────────────────────────

  it('存在する audit_trail_id → 200 + AuditRecord を返す', async () => {
    // CHECK-9: auditStore に追加後に GET すると 200 + 正しいレコードが返ること
    const record = makeRecord({ audit_trail_id: 'trail_ok001' });
    auditStoreModule.auditStore.append(record);

    const res = await callGet('trail_ok001');
    expect(res.status).toBe(200);

    const body = await res.json();
    expect(body.audit_trail_id).toBe('trail_ok001');
    expect(body.final_verdict).toBe('CAPITAL_LIKE');
    expect(body.confidence).toBe(0.95);
    expect(body.model_used).toBe('claude-haiku-4-5');
  });

  it('返却レコードに全フィールドが揃っている', async () => {
    // CHECK-9: AuditRecord の全フィールドがレスポンスに含まれること
    auditStoreModule.auditStore.append(makeRecord({ audit_trail_id: 'trail_full' }));

    const res = await callGet('trail_full');
    const body = await res.json();

    expect(body).toMatchObject({
      audit_trail_id: 'trail_full',
      request_id: 'req_uuid_test001',
      pdf_filename: 'document.pdf',
      line_items_count: 2,
      tax_verdict: 'CAPITAL',
      practice_verdict: 'CAPITAL',
      final_verdict: 'CAPITAL_LIKE',
      elapsed_ms: 1200,
    });
  });

  // 404 系 ──────────────────────────────────────────────────────────────────

  it('存在しない audit_trail_id → 404 を返す', async () => {
    // CHECK-9: ストアにないIDをGETすると 404 + {"error":"Not found"} が返ること
    const res = await callGet('trail_notexist_xyz');
    expect(res.status).toBe(404);

    const body = await res.json();
    expect(body.error).toBe('Not found');
  });

  it('ストアが空のとき → 404 を返す', async () => {
    // CHECK-9: 空ストアで任意の ID を GET すると 404 が返ること
    const res = await callGet('trail_any');
    expect(res.status).toBe(404);
  });

  // 不正 ID 系 ──────────────────────────────────────────────────────────────

  it('空文字列 ID → 400 を返す（バリデーションエラー）', async () => {
    // CHECK-9: 空文字列IDは id バリデーション (!id) に引っかかり 400 が返ること
    const res = await callGet('');
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toBe('Invalid id');
  });

  it('別の ID を追加後も正しい ID でのみ取得できる', async () => {
    // CHECK-9: 複数レコードがある場合、指定 ID のレコードのみ返ること（ID混在なし）
    auditStoreModule.auditStore.append(makeRecord({ audit_trail_id: 'trail_A', final_verdict: 'CAPITAL_LIKE' }));
    auditStoreModule.auditStore.append(makeRecord({ audit_trail_id: 'trail_B', final_verdict: 'EXPENSE_LIKE' }));

    const resA = await callGet('trail_A');
    expect(resA.status).toBe(200);
    const bodyA = await resA.json();
    expect(bodyA.final_verdict).toBe('CAPITAL_LIKE');

    const resB = await callGet('trail_B');
    expect(resB.status).toBe(200);
    const bodyB = await resB.json();
    expect(bodyB.final_verdict).toBe('EXPENSE_LIKE');
  });
});
