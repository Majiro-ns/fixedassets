/**
 * TrainingDataStore: 教師データ SQLite 永続化ストア
 * 根拠: DESIGN_PDF_FIRST_MULTI_AGENT_VER2.md Section 3.4 / cmd_160k_sub2
 *
 * 役割: Practice Agent に渡す TrainingRecord[] を SQLite で永続管理する。
 *       サーバー再起動後もデータが保持される。
 *
 * 設計原則:
 *   - シングルトン export でアプリ全体共有（本番用）
 *   - クラスも export してテストで ':memory:' インスタンスを生成可能
 *   - getAll はコピーを返す（外部変更がストア内部に影響しない）
 *   - better-sqlite3 は同期 API: Next.js Server Components から安全に使える
 *
 * 後方互換性:
 *   - インタフェース（add / addBatch / getAll / clear / size / findSimilar）は変更なし
 *   - テストは new TrainingDataStore() で ':memory:' DB を使用（デフォルト）
 */

import type Database from 'better-sqlite3';
import type { TrainingRecord } from '@/types/training_data';
import { openDatabase, resolveDbPath } from '@/lib/db';

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

// ─── 行型 ────────────────────────────────────────────────────────────────────

interface TrainingRow {
  id: number;
  item: string;
  amount: number;
  label: string;
  notes: string | null;
  created_at: string;
}

// ─── TrainingDataStore クラス ─────────────────────────────────────────────────

/**
 * 教師データを管理する SQLite 永続化ストア。
 * クラスを export することでテストが ':memory:' インスタンスを生成できる。
 */
export class TrainingDataStore {
  private db: Database.Database;
  private stmtInsert: Database.Statement;
  private stmtSelectAll: Database.Statement;
  private stmtCount: Database.Statement;

  /**
   * @param dbPath SQLite ファイルパス。':memory:' でインメモリDB（テスト用）。
   *               省略時は ':memory:'（テスト互換のデフォルト）。
   *               本番シングルトンは resolveDbPath() を明示的に渡す。
   */
  constructor(dbPath: string = ':memory:') {
    this.db = openDatabase(dbPath);

    // プリペアドステートメント（パフォーマンス最適化 + SQLインジェクション防止）
    this.stmtInsert = this.db.prepare(
      `INSERT INTO training_data (item, amount, label, notes) VALUES (?, ?, ?, ?)`,
    );
    this.stmtSelectAll = this.db.prepare(
      `SELECT item, amount, label, notes FROM training_data ORDER BY id ASC`,
    );
    this.stmtCount = this.db.prepare(`SELECT COUNT(*) as cnt FROM training_data`);
  }

  /**
   * 1件追加する。
   */
  add(record: TrainingRecord): void {
    this.stmtInsert.run(record.item, record.amount, record.label, record.notes ?? null);
  }

  /**
   * 複数件を一括追加する（トランザクションで高速化）。
   * /api/import_pdf_training からの一括インポートに使用。
   */
  addBatch(records: TrainingRecord[]): void {
    const insertMany = this.db.transaction((recs: TrainingRecord[]) => {
      for (const r of recs) {
        this.stmtInsert.run(r.item, r.amount, r.label, r.notes ?? null);
      }
    });
    insertMany(records);
  }

  /**
   * 全件取得する（TrainingRecord[] を返す）。
   * 根拠: Section 3.4 "runPracticeAgent の第2引数に渡す"
   */
  getAll(): TrainingRecord[] {
    const rows = this.stmtSelectAll.all() as TrainingRow[];
    return rows.map((r) => ({
      item: r.item,
      amount: r.amount,
      label: r.label as TrainingRecord['label'],
      ...(r.notes != null ? { notes: r.notes } : {}),
    }));
  }

  /**
   * ストアをリセットする（全件削除）。
   * テスト用途 / 再起動シミュレーション。
   */
  clear(): void {
    this.db.prepare(`DELETE FROM training_data`).run();
  }

  /** 登録済み件数を返す。 */
  size(): number {
    const row = this.stmtCount.get() as { cnt: number };
    return row.cnt;
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
    if (this.size() === 0 || topN <= 0) return [];
    const query = keywords.join(' ');
    const all = this.getAll();
    return all
      .map((r) => ({ r, score: calcJaccard(query, r.item) }))
      .sort((a, b) => b.score - a.score)
      .slice(0, topN)
      .map(({ r }) => r);
  }

  /** DB接続を閉じる（テスト後のクリーンアップ用）。 */
  close(): void {
    this.db.close();
  }
}

// ─── シングルトン ────────────────────────────────────────────────────────────

/**
 * アプリケーション全体で共有するシングルトンインスタンス（本番用）。
 * route.ts / import_pdf_training route から参照する。
 *
 * DB パスは SQLITE_DB_PATH 環境変数 または resolveDbPath() で解決される。
 */
export const trainingDataStore = new TrainingDataStore(resolveDbPath());
