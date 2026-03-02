/**
 * GET/POST /api/v2/policies と GET/PUT/DELETE /api/v2/policies/[id] エンドポイントテスト
 * 根拠: cmd_170k_sub2 Phase 3 クライアント別ポリシー管理（F-10）
 *
 * テスト戦略:
 *   - Next.js Route Handler を直接 import して呼び出す
 *   - policyStore シングルトンを beforeEach でリセット（clear()）
 *   - 正常系 / バリデーションエラー / 404 / 409 を検証
 *
 * CHECK-9: 期待値の根拠はすべて API 仕様（route.ts）から直接導出。
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { NextRequest } from 'next/server';
import { GET as listGet, POST } from '../policies/route';
import { GET, PUT, DELETE } from '../policies/[id]/route';
import * as policyStoreModule from '@/lib/policyStore';

// ─── ヘルパー ──────────────────────────────────────────────────────────────

function makeListRequest() {
  return new NextRequest('http://localhost/api/v2/policies');
}

function makePostRequest(body: unknown) {
  return new NextRequest('http://localhost/api/v2/policies', {
    method: 'POST',
    body: JSON.stringify(body),
    headers: { 'Content-Type': 'application/json' },
  });
}

function makeIdRequest(id: string, method = 'GET', body?: unknown) {
  return new NextRequest(`http://localhost/api/v2/policies/${id}`, {
    method,
    ...(body ? { body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } } : {}),
  });
}

function idParams(id: string) {
  return { params: Promise.resolve({ id }) };
}

// ─── テスト ────────────────────────────────────────────────────────────────

describe('GET /api/v2/policies', () => {
  beforeEach(() => {
    policyStoreModule.policyStore.clear();
  });

  it('空のとき → { policies: [] } を返す', async () => {
    const res = await listGet();
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.policies).toEqual([]);
  });

  it('2件あれば 2件のリストを返す', async () => {
    policyStoreModule.policyStore.create({ client_name: 'A社' });
    policyStoreModule.policyStore.create({ client_name: 'B社' });
    const res = await listGet();
    const body = await res.json();
    // CHECK-9: listAll() は id 昇順 → A社 → B社 の順
    expect(body.policies).toHaveLength(2);
    expect(body.policies[0].client_name).toBe('A社');
    expect(body.policies[1].client_name).toBe('B社');
  });
});

describe('POST /api/v2/policies', () => {
  beforeEach(() => {
    policyStoreModule.policyStore.clear();
  });

  it('正常系: ポリシーを作成して 201 を返す', async () => {
    const req = makePostRequest({ client_name: 'C社', threshold_amount: 300_000 });
    const res = await POST(req);
    expect(res.status).toBe(201);
    const body = await res.json();
    expect(body.client_name).toBe('C社');
    expect(body.threshold_amount).toBe(300_000);
    expect(body.id).toBeTypeOf('number');
  });

  it('client_name 省略 → 400 を返す', async () => {
    const req = makePostRequest({ threshold_amount: 200_000 });
    const res = await POST(req);
    // CHECK-9: client_name 必須チェック → 400
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toBeTruthy();
  });

  it('client_name が空文字列 → 400 を返す', async () => {
    const req = makePostRequest({ client_name: '   ' });
    const res = await POST(req);
    expect(res.status).toBe(400);
  });

  it('threshold_amount が負数 → 400 を返す', async () => {
    const req = makePostRequest({ client_name: 'D社', threshold_amount: -1 });
    const res = await POST(req);
    // CHECK-9: threshold_amount < 0 → 400
    expect(res.status).toBe(400);
  });

  it('重複 client_name → 409 を返す', async () => {
    policyStoreModule.policyStore.create({ client_name: 'E社' });
    const req = makePostRequest({ client_name: 'E社' });
    const res = await POST(req);
    // CHECK-9: 重複チェック → 409 Conflict
    expect(res.status).toBe(409);
    const body = await res.json();
    expect(body.error).toContain('E社');
  });

  it('不正 JSON → 400 を返す', async () => {
    const req = new NextRequest('http://localhost/api/v2/policies', {
      method: 'POST',
      body: 'invalid{json',
      headers: { 'Content-Type': 'application/json' },
    });
    const res = await POST(req);
    expect(res.status).toBe(400);
  });
});

describe('GET /api/v2/policies/[id]', () => {
  beforeEach(() => {
    policyStoreModule.policyStore.clear();
  });

  it('存在する ID → 200 + ポリシーオブジェクトを返す', async () => {
    const created = policyStoreModule.policyStore.create({ client_name: 'F社', threshold_amount: 250_000 });
    const req = makeIdRequest(String(created.id));
    const res = await GET(req, idParams(String(created.id)));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.id).toBe(created.id);
    expect(body.client_name).toBe('F社');
    expect(body.threshold_amount).toBe(250_000);
  });

  it('存在しない ID → 404 を返す', async () => {
    const req = makeIdRequest('9999');
    const res = await GET(req, idParams('9999'));
    // CHECK-9: policyStore.getById(9999) === null → 404
    expect(res.status).toBe(404);
    const body = await res.json();
    expect(body.error).toBe('Not found');
  });

  it('数値でない ID → 400 を返す', async () => {
    const req = makeIdRequest('abc');
    const res = await GET(req, idParams('abc'));
    // CHECK-9: Number('abc') は NaN → 400
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toBe('Invalid id');
  });

  it('0 は無効 ID → 400 を返す', async () => {
    const req = makeIdRequest('0');
    const res = await GET(req, idParams('0'));
    // CHECK-9: parseId: n > 0 でなければ null → 400
    expect(res.status).toBe(400);
  });
});

describe('PUT /api/v2/policies/[id]', () => {
  beforeEach(() => {
    policyStoreModule.policyStore.clear();
  });

  it('threshold_amount を更新できる', async () => {
    const created = policyStoreModule.policyStore.create({ client_name: 'G社', threshold_amount: 200_000 });
    const req = makeIdRequest(String(created.id), 'PUT', { threshold_amount: 400_000 });
    const res = await PUT(req, idParams(String(created.id)));
    expect(res.status).toBe(200);
    const body = await res.json();
    // CHECK-9: PUT 後に新しい値が反映される
    expect(body.threshold_amount).toBe(400_000);
    expect(body.client_name).toBe('G社'); // 他フィールドは変わらない
  });

  it('存在しない ID → 404 を返す', async () => {
    const req = makeIdRequest('9999', 'PUT', { threshold_amount: 100_000 });
    const res = await PUT(req, idParams('9999'));
    expect(res.status).toBe(404);
  });

  it('threshold_amount が負数 → 400 を返す', async () => {
    const created = policyStoreModule.policyStore.create({ client_name: 'H社' });
    const req = makeIdRequest(String(created.id), 'PUT', { threshold_amount: -100 });
    const res = await PUT(req, idParams(String(created.id)));
    expect(res.status).toBe(400);
  });
});

describe('DELETE /api/v2/policies/[id]', () => {
  beforeEach(() => {
    policyStoreModule.policyStore.clear();
  });

  it('存在するポリシーを削除できる', async () => {
    const created = policyStoreModule.policyStore.create({ client_name: 'I社' });
    const req = makeIdRequest(String(created.id), 'DELETE');
    const res = await DELETE(req, idParams(String(created.id)));
    expect(res.status).toBe(200);
    const body = await res.json();
    // CHECK-9: DELETE 成功 → { success: true }
    expect(body.success).toBe(true);
  });

  it('削除後は GET で 404 になる', async () => {
    const created = policyStoreModule.policyStore.create({ client_name: 'J社' });
    const deleteReq = makeIdRequest(String(created.id), 'DELETE');
    await DELETE(deleteReq, idParams(String(created.id)));

    const getReq = makeIdRequest(String(created.id));
    const getRes = await GET(getReq, idParams(String(created.id)));
    expect(getRes.status).toBe(404);
  });

  it('存在しない ID → 404 を返す', async () => {
    const req = makeIdRequest('9999', 'DELETE');
    const res = await DELETE(req, idParams('9999'));
    // CHECK-9: policyStore.delete(9999) === false → 404
    expect(res.status).toBe(404);
  });
});
