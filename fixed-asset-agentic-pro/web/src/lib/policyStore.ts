/**
 * PolicyStore: クライアント別ポリシー SQLite 永続化ストア
 * 根拠: cmd_170k_sub2 Phase 3 クライアント別ポリシー管理（F-10）
 *
 * 役割: クライアントごとの判定ポリシー（閾値・キーワード等）を SQLite で管理する。
 *
 * 設計原則:
 *   - シングルトン export でアプリ全体共有（本番用）
 *   - クラスも export してテストで ':memory:' インスタンスを生成可能
 *   - コンストラクタのデフォルトは ':memory:'（テスト互換）
 *   - better-sqlite3 は同期 API: Next.js Route Handlers から安全に使える
 */

import type Database from 'better-sqlite3';
import type { Policy, PolicyRow, CreatePolicyInput, UpdatePolicyInput } from '@/types/policy';
import { openDatabase, resolveDbPath } from '@/lib/db';

// ─── PolicyStore クラス ───────────────────────────────────────────────────────

export class PolicyStore {
  private db: Database.Database;
  private stmtInsert: Database.Statement;
  private stmtSelectById: Database.Statement;
  private stmtSelectByClientName: Database.Statement;
  private stmtSelectAll: Database.Statement;
  private stmtUpdate: Database.Statement;
  private stmtDelete: Database.Statement;
  private stmtCount: Database.Statement;

  constructor(dbPath: string = ':memory:') {
    this.db = openDatabase(dbPath);

    this.stmtInsert = this.db.prepare(`
      INSERT INTO policies (client_name, threshold_amount, keywords_json, rules_json)
      VALUES (?, ?, ?, ?)
    `);

    this.stmtSelectById = this.db.prepare(
      `SELECT * FROM policies WHERE id = ?`,
    );

    this.stmtSelectByClientName = this.db.prepare(
      `SELECT * FROM policies WHERE client_name = ?`,
    );

    this.stmtSelectAll = this.db.prepare(
      `SELECT * FROM policies ORDER BY id ASC`,
    );

    this.stmtUpdate = this.db.prepare(`
      UPDATE policies
      SET client_name      = ?,
          threshold_amount = ?,
          keywords_json    = ?,
          rules_json       = ?,
          updated_at       = datetime('now')
      WHERE id = ?
    `);

    this.stmtDelete = this.db.prepare(`DELETE FROM policies WHERE id = ?`);

    this.stmtCount = this.db.prepare(`SELECT COUNT(*) as cnt FROM policies`);
  }

  // ─── CREATE ──────────────────────────────────────────────────────────────

  /**
   * ポリシーを作成する。
   * @returns 作成したポリシー（id が付与されたもの）
   * @throws client_name が重複している場合は Error
   */
  create(input: CreatePolicyInput): Policy {
    const { client_name, threshold_amount = 200000, keywords = [], rules = {} } = input;
    const result = this.stmtInsert.run(
      client_name,
      threshold_amount,
      JSON.stringify(keywords),
      JSON.stringify(rules),
    );
    const id = result.lastInsertRowid as number;
    return this.getById(id)!;
  }

  // ─── READ ─────────────────────────────────────────────────────────────────

  /** id でポリシーを取得する。見つからない場合は null。 */
  getById(id: number): Policy | null {
    const row = this.stmtSelectById.get(id) as PolicyRow | undefined;
    return row ? this.rowToPolicy(row) : null;
  }

  /** client_name でポリシーを取得する。見つからない場合は null。 */
  getByClientName(clientName: string): Policy | null {
    const row = this.stmtSelectByClientName.get(clientName) as PolicyRow | undefined;
    return row ? this.rowToPolicy(row) : null;
  }

  /** 全ポリシーを id 昇順で返す。 */
  listAll(): Policy[] {
    const rows = this.stmtSelectAll.all() as PolicyRow[];
    return rows.map((r) => this.rowToPolicy(r));
  }

  // ─── UPDATE ──────────────────────────────────────────────────────────────

  /**
   * ポリシーを更新する。
   * @returns 更新後のポリシー。id が存在しない場合は null。
   */
  update(id: number, input: UpdatePolicyInput): Policy | null {
    const existing = this.getById(id);
    if (!existing) return null;

    const client_name = input.client_name ?? existing.client_name;
    const threshold_amount = input.threshold_amount ?? existing.threshold_amount;
    const keywords = input.keywords ?? existing.keywords;
    const rules = input.rules ?? existing.rules;

    this.stmtUpdate.run(
      client_name,
      threshold_amount,
      JSON.stringify(keywords),
      JSON.stringify(rules),
      id,
    );
    return this.getById(id)!;
  }

  // ─── DELETE ──────────────────────────────────────────────────────────────

  /**
   * ポリシーを削除する。
   * @returns 削除に成功した場合は true。id が存在しない場合は false。
   */
  delete(id: number): boolean {
    const result = this.stmtDelete.run(id);
    return result.changes > 0;
  }

  // ─── UTILITY ─────────────────────────────────────────────────────────────

  /** 登録済み件数を返す。 */
  size(): number {
    const row = this.stmtCount.get() as { cnt: number };
    return row.cnt;
  }

  /** ストアをリセットする（テスト用）。 */
  clear(): void {
    this.db.prepare(`DELETE FROM policies`).run();
  }

  /** DB接続を閉じる（テスト後のクリーンアップ用）。 */
  close(): void {
    this.db.close();
  }

  // ─── PRIVATE ─────────────────────────────────────────────────────────────

  private rowToPolicy(row: PolicyRow): Policy {
    return {
      id: row.id,
      client_name: row.client_name,
      threshold_amount: row.threshold_amount,
      keywords: JSON.parse(row.keywords_json) as string[],
      rules: JSON.parse(row.rules_json) as Record<string, unknown>,
      created_at: row.created_at,
      updated_at: row.updated_at,
    };
  }
}

// ─── シングルトン ────────────────────────────────────────────────────────────

export const policyStore = new PolicyStore(resolveDbPath());
