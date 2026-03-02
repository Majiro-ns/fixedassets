/**
 * PolicyStore テスト
 * 根拠: cmd_170k_sub2 Phase 3 クライアント別ポリシー管理（F-10）
 *
 * CHECK-9: 各テストの期待値は F-10 仕様から直接導出:
 *   - デフォルト閾値 200,000 円: PolicyStore.create() のデフォルト値
 *   - UNIQUE 制約: SQLite の client_name UNIQUE 制約
 *   - update()は部分更新: UpdatePolicyInput の undefined フィールドを維持
 *   - delete() は存在しない ID に対して false を返す
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { PolicyStore } from '@/lib/policyStore';

describe('PolicyStore', () => {
  let store: PolicyStore;

  beforeEach(() => {
    // テスト用インメモリ DB（テスト間で独立）
    store = new PolicyStore(':memory:');
  });

  afterEach(() => {
    store.close();
  });

  // ─── CREATE ──────────────────────────────────────────────────────────────

  describe('create()', () => {
    it('最小入力でポリシーを作成できる', () => {
      const policy = store.create({ client_name: 'A社' });
      expect(policy.id).toBeTypeOf('number');
      expect(policy.client_name).toBe('A社');
      // CHECK-9: デフォルト閾値は 200,000 円（policyStore.ts デフォルト値）
      expect(policy.threshold_amount).toBe(200_000);
      expect(policy.keywords).toEqual([]);
      expect(policy.rules).toEqual({});
      expect(policy.created_at).toBeTruthy();
      expect(policy.updated_at).toBeTruthy();
    });

    it('全フィールドを指定してポリシーを作成できる', () => {
      const policy = store.create({
        client_name: 'B社',
        threshold_amount: 300_000,
        keywords: ['修繕', 'メンテナンス'],
        rules: { allowSmallExpense: true },
      });
      expect(policy.client_name).toBe('B社');
      expect(policy.threshold_amount).toBe(300_000);
      expect(policy.keywords).toEqual(['修繕', 'メンテナンス']);
      expect(policy.rules).toEqual({ allowSmallExpense: true });
    });

    it('client_name が重複するとエラーをスローする', () => {
      store.create({ client_name: 'A社' });
      // CHECK-9: SQLite UNIQUE 制約エラー → Error
      expect(() => store.create({ client_name: 'A社' })).toThrow();
    });

    it('IDは自動インクリメントされる', () => {
      const p1 = store.create({ client_name: 'A社' });
      const p2 = store.create({ client_name: 'B社' });
      expect(p2.id).toBe(p1.id + 1);
    });
  });

  // ─── READ ─────────────────────────────────────────────────────────────────

  describe('getById()', () => {
    it('存在するIDでポリシーを取得できる', () => {
      const created = store.create({ client_name: 'A社', threshold_amount: 250_000 });
      const fetched = store.getById(created.id);
      expect(fetched).not.toBeNull();
      expect(fetched!.id).toBe(created.id);
      expect(fetched!.threshold_amount).toBe(250_000);
    });

    it('存在しないIDは null を返す', () => {
      const result = store.getById(9999);
      expect(result).toBeNull();
    });
  });

  describe('getByClientName()', () => {
    it('client_name でポリシーを取得できる', () => {
      store.create({ client_name: 'C社' });
      const fetched = store.getByClientName('C社');
      expect(fetched).not.toBeNull();
      expect(fetched!.client_name).toBe('C社');
    });

    it('存在しない client_name は null を返す', () => {
      const result = store.getByClientName('存在しない会社');
      expect(result).toBeNull();
    });
  });

  describe('listAll()', () => {
    it('空のストアは空配列を返す', () => {
      expect(store.listAll()).toEqual([]);
    });

    it('複数ポリシーをID昇順で返す', () => {
      store.create({ client_name: 'A社' });
      store.create({ client_name: 'B社' });
      store.create({ client_name: 'C社' });
      const list = store.listAll();
      expect(list).toHaveLength(3);
      // CHECK-9: ORDER BY id ASC であることを確認
      expect(list[0].client_name).toBe('A社');
      expect(list[1].client_name).toBe('B社');
      expect(list[2].client_name).toBe('C社');
    });
  });

  // ─── UPDATE ──────────────────────────────────────────────────────────────

  describe('update()', () => {
    it('threshold_amount を更新できる', () => {
      const created = store.create({ client_name: 'A社', threshold_amount: 200_000 });
      const updated = store.update(created.id, { threshold_amount: 300_000 });
      expect(updated).not.toBeNull();
      // CHECK-9: 更新後の値が反映されること
      expect(updated!.threshold_amount).toBe(300_000);
      // 他のフィールドは変わらない（部分更新）
      expect(updated!.client_name).toBe('A社');
    });

    it('keywords を更新できる', () => {
      const created = store.create({ client_name: 'D社', keywords: ['旧'] });
      const updated = store.update(created.id, { keywords: ['新', '追加'] });
      expect(updated!.keywords).toEqual(['新', '追加']);
    });

    it('rules を更新できる', () => {
      const created = store.create({ client_name: 'E社', rules: { a: 1 } });
      const updated = store.update(created.id, { rules: { b: 2 } });
      expect(updated!.rules).toEqual({ b: 2 });
    });

    it('存在しない ID は null を返す', () => {
      const result = store.update(9999, { threshold_amount: 100_000 });
      expect(result).toBeNull();
    });

    it('undefined フィールドは既存値を保持する（部分更新）', () => {
      const created = store.create({
        client_name: 'F社',
        threshold_amount: 200_000,
        keywords: ['key1'],
      });
      // client_name だけ更新（他は undefined）
      const updated = store.update(created.id, { client_name: 'F社(改)' });
      expect(updated!.client_name).toBe('F社(改)');
      // CHECK-9: 他フィールドはそのまま維持
      expect(updated!.threshold_amount).toBe(200_000);
      expect(updated!.keywords).toEqual(['key1']);
    });
  });

  // ─── DELETE ──────────────────────────────────────────────────────────────

  describe('delete()', () => {
    it('存在するポリシーを削除できる', () => {
      const created = store.create({ client_name: 'A社' });
      const result = store.delete(created.id);
      expect(result).toBe(true);
      expect(store.getById(created.id)).toBeNull();
    });

    it('存在しない ID は false を返す', () => {
      const result = store.delete(9999);
      // CHECK-9: result.changes === 0 → false
      expect(result).toBe(false);
    });

    it('削除後は listAll に含まれない', () => {
      const p1 = store.create({ client_name: 'A社' });
      store.create({ client_name: 'B社' });
      store.delete(p1.id);
      const list = store.listAll();
      expect(list).toHaveLength(1);
      expect(list[0].client_name).toBe('B社');
    });
  });

  // ─── UTILITY ─────────────────────────────────────────────────────────────

  describe('size()', () => {
    it('初期状態は0', () => {
      expect(store.size()).toBe(0);
    });

    it('追加するたびに増える', () => {
      store.create({ client_name: 'A社' });
      expect(store.size()).toBe(1);
      store.create({ client_name: 'B社' });
      expect(store.size()).toBe(2);
    });
  });

  describe('clear()', () => {
    it('全ポリシーを削除する', () => {
      store.create({ client_name: 'A社' });
      store.create({ client_name: 'B社' });
      store.clear();
      expect(store.size()).toBe(0);
      expect(store.listAll()).toEqual([]);
    });
  });

  // ─── JSON シリアライズ ─────────────────────────────────────────────────

  describe('JSON シリアライズ / デシリアライズ', () => {
    it('keywords: 文字列配列が正しく保存・復元される', () => {
      const keywords = ['修繕', 'メンテナンス', '定期点検'];
      const created = store.create({ client_name: '配列テスト', keywords });
      const fetched = store.getById(created.id)!;
      expect(fetched.keywords).toEqual(keywords);
    });

    it('rules: ネストされたオブジェクトが正しく保存・復元される', () => {
      const rules = { key1: { nested: [1, 2, 3] }, flag: true };
      const created = store.create({ client_name: 'JSONテスト', rules });
      const fetched = store.getById(created.id)!;
      expect(fetched.rules).toEqual(rules);
    });
  });
});
