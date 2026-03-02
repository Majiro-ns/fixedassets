/**
 * persistence.test.ts
 * SQLite 永続化テスト（cmd_160k_sub2）
 *
 * 検証対象:
 *   1. 再起動シミュレーション: ストア再初期化後もデータが残っている（ファイルDB）
 *   2. 大量データ挿入（1000件）のパフォーマンス: 2秒以内に完了
 *   3. 同時書き込みシミュレーション: 複数の append が競合せずに完了
 *   4. TransactionDataStore: addBatch がトランザクションで高速に動作
 *   5. AuditTrailStore: INSERT OR REPLACE（同じIDの上書き）が正しく動作
 *
 * テスト戦略:
 *   - 再起動シミュレーション: 一時ファイル DB を作成→同じパスで再オープンして確認
 *   - パフォーマンス: ':memory:' DB で 1000件挿入し処理時間を計測
 *   - 同時書き込み: better-sqlite3 は同期API（シリアル実行）なので競合は発生しないが
 *     複数の append/add が全て記録されることを確認
 *
 * CHECK-9: テスト期待値根拠
 *   - 再起動後データ残存: SQLite WAL モードで書き込み済みデータは再起動後も保持
 *   - 1000件: better-sqlite3 の通常速度は 100k件/秒以上。2秒 = 余裕を持った閾値
 *   - INSERT OR REPLACE: SQLite の挙動として同一 PRIMARY KEY は上書きされる
 */

import { describe, it, expect, afterEach } from 'vitest';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { TrainingDataStore } from '../trainingDataStore';
import { AuditTrailStore } from '../auditStore';
import type { TrainingRecord } from '@/types/training_data';
import type { AuditRecord } from '@/types/audit_trail';

// ─── テストデータファクトリ ───────────────────────────────────────────────────

function makeTrainingRecord(overrides?: Partial<TrainingRecord>): TrainingRecord {
  return { item: 'ノートPC', amount: 250000, label: '固定資産', ...overrides };
}

function makeAuditRecord(overrides?: Partial<AuditRecord>): AuditRecord {
  return {
    audit_trail_id: 'trail_test001',
    request_id: 'req_uuid_001',
    timestamp: '2026-03-03T10:00:00.000Z',
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

// ─── 一時ファイルDBユーティリティ ─────────────────────────────────────────────

function makeTempDbPath(): string {
  return path.join(os.tmpdir(), `fixed-asset-test-${Date.now()}-${Math.random().toString(36).slice(2)}.db`);
}

// ─── 1. 再起動シミュレーション: TrainingDataStore ────────────────────────────

describe('永続化: TrainingDataStore 再起動シミュレーション', () => {
  let dbPath: string;

  afterEach(() => {
    // 一時ファイルを削除
    if (dbPath && fs.existsSync(dbPath)) {
      try { fs.unlinkSync(dbPath); } catch { /* ignore */ }
      try { fs.unlinkSync(dbPath + '-wal'); } catch { /* ignore */ }
      try { fs.unlinkSync(dbPath + '-shm'); } catch { /* ignore */ }
    }
  });

  it('ファイルDBに追加したデータは新しいインスタンスでも取得できる（再起動後永続化）', () => {
    // CHECK-9: SQLite ファイル DB に書き込んだデータは、接続を閉じて再度開いても残る
    dbPath = makeTempDbPath();

    // 第1インスタンス: データを書き込んで閉じる
    const store1 = new TrainingDataStore(dbPath);
    store1.add(makeTrainingRecord({ item: 'サーバー設備', amount: 1_000_000, label: '固定資産' }));
    store1.add(makeTrainingRecord({ item: '消耗品費', amount: 3_000, label: '費用' }));
    expect(store1.size()).toBe(2);
    store1.close();

    // 第2インスタンス: 同じパスで再オープン → データが残っていること
    const store2 = new TrainingDataStore(dbPath);
    expect(store2.size()).toBe(2);
    const all = store2.getAll();
    expect(all.map((r) => r.item)).toContain('サーバー設備');
    expect(all.map((r) => r.item)).toContain('消耗品費');
    store2.close();
  });

  it('clear後に再起動すると空のストアになる', () => {
    // CHECK-9: clear = DELETE FROM training_data → 全削除。再起動後も空
    dbPath = makeTempDbPath();

    const store1 = new TrainingDataStore(dbPath);
    store1.add(makeTrainingRecord());
    store1.clear();
    store1.close();

    const store2 = new TrainingDataStore(dbPath);
    expect(store2.size()).toBe(0);
    store2.close();
  });
});

// ─── 2. 再起動シミュレーション: AuditTrailStore ──────────────────────────────

describe('永続化: AuditTrailStore 再起動シミュレーション', () => {
  let dbPath: string;

  afterEach(() => {
    if (dbPath && fs.existsSync(dbPath)) {
      try { fs.unlinkSync(dbPath); } catch { /* ignore */ }
      try { fs.unlinkSync(dbPath + '-wal'); } catch { /* ignore */ }
      try { fs.unlinkSync(dbPath + '-shm'); } catch { /* ignore */ }
    }
  });

  it('ファイルDBに append したレコードは新しいインスタンスでも getById できる', () => {
    // CHECK-9: SQLite INSERT OR REPLACE で書き込んだ行は再起動後も残る
    dbPath = makeTempDbPath();

    const store1 = new AuditTrailStore(dbPath);
    store1.append(makeAuditRecord({ audit_trail_id: 'trail_persist_001' }));
    store1.close();

    const store2 = new AuditTrailStore(dbPath);
    const record = store2.getById('trail_persist_001');
    expect(record).not.toBeNull();
    expect(record?.final_verdict).toBe('CAPITAL_LIKE');
    expect(record?.confidence).toBe(0.95);
    store2.close();
  });

  it('複数レコードを追加して再起動後も全件取得できる', () => {
    dbPath = makeTempDbPath();

    const store1 = new AuditTrailStore(dbPath);
    store1.append(makeAuditRecord({ audit_trail_id: 'trail_A', final_verdict: 'CAPITAL_LIKE' }));
    store1.append(makeAuditRecord({ audit_trail_id: 'trail_B', final_verdict: 'EXPENSE_LIKE' }));
    store1.append(makeAuditRecord({ audit_trail_id: 'trail_C', final_verdict: 'UNCERTAIN' }));
    store1.close();

    const store2 = new AuditTrailStore(dbPath);
    expect(store2.size()).toBe(3);
    const list = store2.list();
    expect(list.map((r) => r.audit_trail_id)).toContain('trail_A');
    expect(list.map((r) => r.audit_trail_id)).toContain('trail_B');
    expect(list.map((r) => r.audit_trail_id)).toContain('trail_C');
    store2.close();
  });
});

// ─── 3. パフォーマンステスト（1000件挿入）────────────────────────────────────

describe('永続化: パフォーマンステスト（1000件）', () => {
  it('TrainingDataStore: 1000件 addBatch が 2秒以内に完了する', () => {
    // CHECK-9: better-sqlite3 のバルク挿入は高速（通常 100k件/秒以上）
    //          トランザクションを使うことで N 回の BEGIN/COMMIT を 1 回にまとめる
    const store = new TrainingDataStore(':memory:');
    const records: TrainingRecord[] = Array.from({ length: 1000 }, (_, i) => ({
      item: `テスト品目${i}`,
      amount: i * 1000,
      label: i % 2 === 0 ? '固定資産' : '費用',
    }));

    const start = Date.now();
    store.addBatch(records);
    const elapsed = Date.now() - start;

    expect(store.size()).toBe(1000);
    expect(elapsed).toBeLessThan(2000); // 2秒以内
  });

  it('AuditTrailStore: 1000件 append が 2秒以内に完了する', () => {
    // CHECK-9: INSERT OR REPLACE + WAL モードで高速書き込み
    const store = new AuditTrailStore(':memory:');

    const start = Date.now();
    for (let i = 0; i < 1000; i++) {
      store.append(makeAuditRecord({
        audit_trail_id: `trail_perf_${i.toString().padStart(4, '0')}`,
        timestamp: new Date(2026, 2, 3, 0, 0, i).toISOString(),
      }));
    }
    const elapsed = Date.now() - start;

    expect(store.size()).toBe(1000);
    expect(elapsed).toBeLessThan(2000); // 2秒以内
  });

  it('TrainingDataStore: 1000件取得（getAll）が 500ms 以内に完了する', () => {
    const store = new TrainingDataStore(':memory:');
    store.addBatch(
      Array.from({ length: 1000 }, (_, i) => ({
        item: `品目${i}`,
        amount: i * 100,
        label: '固定資産' as const,
      })),
    );

    const start = Date.now();
    const all = store.getAll();
    const elapsed = Date.now() - start;

    expect(all).toHaveLength(1000);
    expect(elapsed).toBeLessThan(500);
  });
});

// ─── 4. 同時書き込みシミュレーション ─────────────────────────────────────────

describe('永続化: 同時書き込みシミュレーション', () => {
  it('TrainingDataStore: 連続 100 回の add が全件記録される', () => {
    // CHECK-9: better-sqlite3 は同期 API（シリアル実行）なので競合は発生しない
    //          100回の add が全て記録されることを確認（データ欠損がないこと）
    const store = new TrainingDataStore(':memory:');
    for (let i = 0; i < 100; i++) {
      store.add(makeTrainingRecord({ item: `品目${i}`, amount: i * 1000 }));
    }
    expect(store.size()).toBe(100);
    const all = store.getAll();
    for (let i = 0; i < 100; i++) {
      expect(all.some((r) => r.item === `品目${i}`)).toBe(true);
    }
  });

  it('AuditTrailStore: 連続 100 回の append が全件記録される', () => {
    const store = new AuditTrailStore(':memory:');
    for (let i = 0; i < 100; i++) {
      store.append(makeAuditRecord({
        audit_trail_id: `trail_concurrent_${i.toString().padStart(3, '0')}`,
      }));
    }
    expect(store.size()).toBe(100);
  });
});

// ─── 5. INSERT OR REPLACE（上書き）テスト ────────────────────────────────────

describe('永続化: AuditTrailStore INSERT OR REPLACE', () => {
  it('同じ audit_trail_id で append すると上書きされ size が増えない', () => {
    // CHECK-9: INSERT OR REPLACE → 既存行を削除して再挿入。size は変わらない
    const store = new AuditTrailStore(':memory:');
    store.append(makeAuditRecord({ audit_trail_id: 'trail_overwrite', final_verdict: 'CAPITAL_LIKE' }));
    store.append(makeAuditRecord({ audit_trail_id: 'trail_overwrite', final_verdict: 'EXPENSE_LIKE' }));

    expect(store.size()).toBe(1);
    const record = store.getById('trail_overwrite');
    expect(record?.final_verdict).toBe('EXPENSE_LIKE'); // 後の値が保持される
  });
});
