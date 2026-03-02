/**
 * TrainingDataStore ユニットテスト
 * 根拠: DESIGN_PDF_FIRST_MULTI_AGENT_VER2.md Section 3.4
 *
 * テスト戦略:
 *   - TrainingDataStore クラスのフレッシュインスタンスを各テストで生成（シングルトン汚染防止）
 *   - 基本CRUD: add / addBatch / getAll / clear / size
 *   - findSimilar: Jaccard 類似度降順ソート・topN 制限・空ストア
 *
 * CHECK-9: 全テストに根拠コメントを記載。
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { TrainingDataStore } from '../trainingDataStore';
import type { TrainingRecord } from '@/types/training_data';

// ─── テストデータ ───────────────────────────────────────────────────────────

const record1: TrainingRecord = { item: 'ノートPC', amount: 250000, label: '固定資産' };
const record2: TrainingRecord = { item: '消耗品費', amount: 3000, label: '費用' };
const record3: TrainingRecord = { item: 'デスクトップPC Dell', amount: 180000, label: '固定資産', notes: '取得価額10万円以上' };
const record4: TrainingRecord = { item: 'エアコン', amount: 150000, label: '固定資産' };
const record5: TrainingRecord = { item: 'コピー用紙', amount: 5000, label: '費用' };

// ─── 基本CRUD テスト ────────────────────────────────────────────────────────

describe('TrainingDataStore: 基本CRUD', () => {
  let store: TrainingDataStore;

  beforeEach(() => {
    store = new TrainingDataStore();
  });

  it('空ストアの getAll は [] を返す', () => {
    // CHECK-9: 初期状態で records=[] のため空配列が返ること
    expect(store.getAll()).toEqual([]);
    expect(store.size()).toBe(0);
  });

  it('add → getAll で追加したレコードが取得できる', () => {
    // CHECK-9: add後にgetAllするとレコードが含まれること（Section 3.4 ストア設計）
    store.add(record1);
    const result = store.getAll();
    expect(result).toHaveLength(1);
    expect(result[0].item).toBe('ノートPC');
    expect(result[0].amount).toBe(250000);
    expect(result[0].label).toBe('固定資産');
  });

  it('getAll はコピーを返す（外部変更がストア内部に影響しない）', () => {
    // CHECK-9: getAll の返り値を破壊的変更してもストア内部が変わらないこと
    store.add(record1);
    const result = store.getAll();
    result.push(record2); // 外部で追加
    expect(store.size()).toBe(1); // ストア内部は変化しない
  });

  it('clear でストアが空になる', () => {
    // CHECK-9: add後 clear すると size=0 / getAll=[] になること
    store.add(record1);
    store.add(record2);
    expect(store.size()).toBe(2);
    store.clear();
    expect(store.size()).toBe(0);
    expect(store.getAll()).toEqual([]);
  });

  it('size は件数を正しく返す（add 複数回）', () => {
    // CHECK-9: 3件追加後に size=3 であること
    store.add(record1);
    store.add(record2);
    store.add(record3);
    expect(store.size()).toBe(3);
  });

  it('addBatch で複数件を一括追加できる', () => {
    // CHECK-9: addBatch([r1, r2, r3]) 後に size=3 / getAll が全件含むこと
    store.addBatch([record1, record2, record3]);
    expect(store.size()).toBe(3);
    const all = store.getAll();
    expect(all.map((r) => r.item)).toContain('ノートPC');
    expect(all.map((r) => r.item)).toContain('消耗品費');
    expect(all.map((r) => r.item)).toContain('デスクトップPC Dell');
  });

  it('addBatch の後の add で合計件数が加算される', () => {
    // CHECK-9: addBatch(2件) + add(1件) = size(3)
    store.addBatch([record1, record2]);
    store.add(record3);
    expect(store.size()).toBe(3);
  });
});

// ─── findSimilar テスト ─────────────────────────────────────────────────────

describe('TrainingDataStore: findSimilar（Jaccard類似度）', () => {
  let store: TrainingDataStore;

  beforeEach(() => {
    store = new TrainingDataStore();
  });

  it('空ストアの findSimilar は [] を返す', () => {
    // CHECK-9: 空ストアから findSimilar しても例外なく [] が返ること
    const result = store.findSimilar(['ノートPC'], 5);
    expect(result).toEqual([]);
  });

  it('完全一致するキーワードのレコードが最上位に来る（Jaccard=1.0）', () => {
    // CHECK-9 手計算検算: query="ノートpc" vs record1.item="ノートpc" → 1/1=1.0（最高スコア）
    //                     query="ノートpc" vs record2.item="消耗品費" → 0/2=0.0
    store.add(record1); // ノートPC
    store.add(record2); // 消耗品費
    const result = store.findSimilar(['ノートPC'], 2);
    expect(result[0].item).toBe('ノートPC');
  });

  it('topN を超えるレコードは返さない', () => {
    // CHECK-9: 5件ストアで topN=2 → 2件のみ返ること
    store.addBatch([record1, record2, record3, record4, record5]);
    const result = store.findSimilar(['PC'], 2);
    expect(result).toHaveLength(2);
  });

  it('類似度降順でソートされる（PC系が上位に来る）', () => {
    // CHECK-9 手計算:
    //   query="ノートpc デスクトップpc" tokens: {"ノートpc", "デスクトップpc"}
    //   record1 "ノートpc" → intersection=1, union=2 → 0.5
    //   record3 "デスクトップpc dell" → intersection=1, union=3 → 0.33
    //   record2 "消耗品費" → intersection=0, union=3 → 0.0
    //   → record1 > record3 > record2 の順になること
    store.add(record2); // 消耗品費 → スコア低
    store.add(record3); // デスクトップPC Dell
    store.add(record1); // ノートPC → スコア最高
    const result = store.findSimilar(['ノートPC', 'デスクトップPC'], 3);
    expect(result[0].item).toBe('ノートPC');
    // 2位は record3（デスクトップPC Dell）> record2（消耗品費）
    expect(result[2].item).toBe('消耗品費');
  });

  it('keywords が空リストでも動作する（全件 similarity=0 で返す）', () => {
    // CHECK-9: 空キーワードは calcJaccard("", item) → 0.0 → 全件スコア0でそのまま返る
    store.add(record1);
    store.add(record2);
    const result = store.findSimilar([], 5);
    // 例外なく返ること、件数は 2 以内
    expect(result.length).toBeLessThanOrEqual(2);
  });

  it('add → findSimilar で追加したレコードが正しく選択される（連携確認）', () => {
    // CHECK-9: add後に findSimilar すると該当レコードが返ること（Section 3.4 Practice Agent接続）
    store.add(record4); // エアコン
    store.add(record5); // コピー用紙
    const result = store.findSimilar(['エアコン'], 1);
    expect(result).toHaveLength(1);
    expect(result[0].item).toBe('エアコン');
  });

  it('topN=0 のとき [] を返す', () => {
    // CHECK-9: 境界値テスト。topN <= 0 は即座に [] を返す
    store.add(record1);
    const result = store.findSimilar(['ノートPC'], 0);
    expect(result).toEqual([]);
  });
});
