/**
 * TrainingDataStore: 教師データ インメモリ永続化ストア
 * 根拠: DESIGN_PDF_FIRST_MULTI_AGENT_VER2.md Section 3.4
 *
 * 役割: Practice Agent に渡す TrainingRecord[] を永続管理する。
 *       Phase 1 MVP はインメモリ（シングルトン）。
 *       Phase 2 以降で DB / Redis 等に差し替え可能な設計。
 *
 * 設計原則:
 *   - シングルトン export でアプリ全体共有
 *   - クラスも export してテストで新鮮なインスタンスを生成可能
 *   - getAll はコピーを返す（外部変更がストア内部に影響しない）
 */

import type { TrainingRecord } from '@/types/training_data';

// ─── Jaccard 類似度計算 ──────────────────────────────────────────────────────

/**
 * 2 つの文字列間の Jaccard 係数を算出する。
 * 根拠: Section 3.4 "教師データ（TrainingRecord）の活用パターン"
 * CHECK-9: practiceAgent.ts の calcSimilarity と同一ロジック
 *
 * CHECK-7b 手計算検証:
 *   "ノートPC" vs "ノートPC" → tokens: {"ノートpc"} / {"ノートpc"} → 1/1 = 1.0
 *   "エアコン" vs "コピー用紙" → tokens: {"エアコン"} / {"コピー用紙"} → 0/2 = 0.0
 */
function calcJaccard(a: string, b: string): number {
  if (!a || !b) return 0;

  const tokenize = (s: string): Set<string> =>
    new Set(
      s
        .toLowerCase()
        .split(/[\s\u3000、。・「」【】（）()¥,・\d]+/)
        .filter((t) => t.length > 0),
    );

  const setA = tokenize(a);
  const setB = tokenize(b);

  if (setA.size === 0 || setB.size === 0) return 0;

  let intersection = 0;
  for (const t of setA) {
    if (setB.has(t)) intersection++;
  }

  const union = setA.size + setB.size - intersection;
  return union === 0 ? 0 : intersection / union;
}

// ─── TrainingDataStore クラス ─────────────────────────────────────────────────

/**
 * 教師データを管理するインメモリストア。
 * クラスを export することでテストが fresh インスタンスを生成できる。
 */
export class TrainingDataStore {
  private records: TrainingRecord[] = [];

  /**
   * 1件追加する。
   * 内部配列にはコピーを格納（外部変更からの保護）。
   */
  add(record: TrainingRecord): void {
    this.records.push({ ...record });
  }

  /**
   * 複数件を一括追加する。
   * /api/import_pdf_training からの一括インポートに使用。
   */
  addBatch(records: TrainingRecord[]): void {
    for (const r of records) {
      this.records.push({ ...r });
    }
  }

  /**
   * 全件取得する（シャローコピーを返す）。
   * 根拠: Section 3.4 "runPracticeAgent の第2引数に渡す"
   */
  getAll(): TrainingRecord[] {
    return [...this.records];
  }

  /**
   * ストアをリセットする。
   * テスト用途 / 再起動シミュレーション。
   */
  clear(): void {
    this.records = [];
  }

  /** 登録済み件数を返す。 */
  size(): number {
    return this.records.length;
  }

  /**
   * キーワード群に最も類似した教師データを topN 件返す。
   * 根拠: Section 3.4 "few-shot 選択（Jaccard 類似度降順）"
   *
   * @param keywords  検索キーワード群（品目名のトークン等）
   * @param topN      最大取得件数
   * @returns Jaccard 類似度降順でソートされた TrainingRecord[]（topN 件以内）
   *
   * CHECK-9: 類似度スコアは calcJaccard（上記）で算出。
   *          空ストアの場合は即座に [] を返す。
   */
  findSimilar(keywords: string[], topN: number): TrainingRecord[] {
    if (this.records.length === 0 || topN <= 0) return [];
    const query = keywords.join(' ');
    return [...this.records]
      .map((r) => ({ r, score: calcJaccard(query, r.item) }))
      .sort((a, b) => b.score - a.score)
      .slice(0, topN)
      .map(({ r }) => r);
  }
}

// ─── シングルトン ────────────────────────────────────────────────────────────

/**
 * アプリケーション全体で共有するシングルトンインスタンス。
 * route.ts / import_pdf_training route から参照する。
 *
 * Phase 2 拡張点: DB / Redis 永続化への置換はこの export を差し替えるだけで済む。
 */
export const trainingDataStore = new TrainingDataStore();
