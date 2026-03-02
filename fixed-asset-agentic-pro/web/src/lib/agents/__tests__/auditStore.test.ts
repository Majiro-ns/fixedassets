/**
 * AuditTrailStore ユニットテスト
 * 根拠: DESIGN_PDF_FIRST_MULTI_AGENT_VER2.md Phase 2 Audit Trail基盤
 *
 * テスト戦略:
 *   - AuditTrailStore クラスの fresh インスタンスを各テストで生成（シングルトン汚染防止）
 *   - 基本CRUD: append / getById / list / clear / size
 *   - コピー返却: 外部変更がストア内部に影響しない
 *   - list 順序: 最新順（逆挿入順）
 *
 * CHECK-9: 全テストに根拠コメントを記載。
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { AuditTrailStore } from '../auditStore';
import type { AuditRecord } from '@/types/audit_trail';

// ─── テストデータ ───────────────────────────────────────────────────────────

function makeRecord(overrides?: Partial<AuditRecord>): AuditRecord {
  return {
    audit_trail_id: 'trail_abc123',
    request_id: 'req_uuid_001',
    timestamp: '2026-03-02T10:00:00.000Z',
    pdf_filename: 'document.pdf',
    line_items_count: 1,
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

// ─── 基本CRUD テスト ────────────────────────────────────────────────────────

describe('AuditTrailStore: 基本CRUD', () => {
  let store: AuditTrailStore;

  beforeEach(() => {
    store = new AuditTrailStore();
  });

  it('空ストアの size は 0 を返す', () => {
    // CHECK-9: 初期状態で records が空のため size=0
    expect(store.size()).toBe(0);
  });

  it('空ストアの list は [] を返す', () => {
    // CHECK-9: 初期状態で空配列が返ること
    expect(store.list()).toEqual([]);
  });

  it('空ストアの getById は null を返す', () => {
    // CHECK-9: 存在しない ID で getById すると null が返ること
    expect(store.getById('trail_notexist')).toBeNull();
  });

  it('append → getById で追加したレコードが取得できる', () => {
    // CHECK-9: append 後に getById するとレコードが返ること（基本フロー）
    const record = makeRecord();
    store.append(record);
    const result = store.getById('trail_abc123');
    expect(result).not.toBeNull();
    expect(result?.audit_trail_id).toBe('trail_abc123');
    expect(result?.final_verdict).toBe('CAPITAL_LIKE');
    expect(result?.confidence).toBe(0.95);
  });

  it('append → size が 1 になる', () => {
    // CHECK-9: 1件追加後に size=1
    store.append(makeRecord());
    expect(store.size()).toBe(1);
  });

  it('存在しない ID で getById は null を返す', () => {
    // CHECK-9: audit_trail_id が一致しないキーは null
    store.append(makeRecord({ audit_trail_id: 'trail_abc123' }));
    expect(store.getById('trail_xyz999')).toBeNull();
  });

  it('clear でストアが空になる', () => {
    // CHECK-9: append後 clear すると size=0 / list=[] になること
    store.append(makeRecord({ audit_trail_id: 'trail_001' }));
    store.append(makeRecord({ audit_trail_id: 'trail_002' }));
    expect(store.size()).toBe(2);
    store.clear();
    expect(store.size()).toBe(0);
    expect(store.list()).toEqual([]);
  });

  it('複数レコードを append できる', () => {
    // CHECK-9: 3件追加後に size=3
    store.append(makeRecord({ audit_trail_id: 'trail_001' }));
    store.append(makeRecord({ audit_trail_id: 'trail_002' }));
    store.append(makeRecord({ audit_trail_id: 'trail_003' }));
    expect(store.size()).toBe(3);
  });
});

// ─── list 順序テスト ─────────────────────────────────────────────────────────

describe('AuditTrailStore: list 順序・limit', () => {
  let store: AuditTrailStore;

  beforeEach(() => {
    store = new AuditTrailStore();
  });

  it('list は最新順（逆挿入順）で返す', () => {
    // CHECK-9: 挿入順 [001, 002, 003] → list は [003, 002, 001] の逆順であること
    store.append(makeRecord({ audit_trail_id: 'trail_001' }));
    store.append(makeRecord({ audit_trail_id: 'trail_002' }));
    store.append(makeRecord({ audit_trail_id: 'trail_003' }));
    const result = store.list();
    expect(result[0].audit_trail_id).toBe('trail_003');
    expect(result[1].audit_trail_id).toBe('trail_002');
    expect(result[2].audit_trail_id).toBe('trail_001');
  });

  it('list(2) は先頭 2 件のみ返す', () => {
    // CHECK-9: limit=2 → 最新2件のみ返ること
    store.append(makeRecord({ audit_trail_id: 'trail_001' }));
    store.append(makeRecord({ audit_trail_id: 'trail_002' }));
    store.append(makeRecord({ audit_trail_id: 'trail_003' }));
    const result = store.list(2);
    expect(result).toHaveLength(2);
    expect(result[0].audit_trail_id).toBe('trail_003');
    expect(result[1].audit_trail_id).toBe('trail_002');
  });

  it('list(0) は [] を返す', () => {
    // CHECK-9: 境界値テスト。limit=0 は空配列
    store.append(makeRecord({ audit_trail_id: 'trail_001' }));
    expect(store.list(0)).toEqual([]);
  });
});

// ─── コピー返却テスト ─────────────────────────────────────────────────────────

describe('AuditTrailStore: コピー返却（外部変更からの保護）', () => {
  let store: AuditTrailStore;

  beforeEach(() => {
    store = new AuditTrailStore();
  });

  it('getById の返り値を変更してもストア内部に影響しない', () => {
    // CHECK-9: getById は内部 Map の参照ではなくコピーを返す
    store.append(makeRecord({ audit_trail_id: 'trail_copy', confidence: 0.95 }));
    const result = store.getById('trail_copy')!;
    result.confidence = 0.00; // 外部変更
    const again = store.getById('trail_copy')!;
    expect(again.confidence).toBe(0.95); // ストア内部は変化しない
  });

  it('list の返り値を変更してもストア内部に影響しない', () => {
    // CHECK-9: list は各レコードのコピーを返す
    store.append(makeRecord({ audit_trail_id: 'trail_list', model_used: 'haiku' }));
    const listed = store.list();
    listed[0].model_used = 'corrupted';
    const again = store.getById('trail_list')!;
    expect(again.model_used).toBe('haiku'); // ストア内部は変化しない
  });
});
