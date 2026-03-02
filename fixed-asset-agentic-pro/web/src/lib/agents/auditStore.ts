/**
 * AuditTrailStore: 監査証跡 SQLite 永続化ストア
 * 根拠: DESIGN_PDF_FIRST_MULTI_AGENT_VER2.md Phase 2 Audit Trail基盤 / cmd_160k_sub2
 *
 * 役割: classify_pdf の判定結果を SQLite で永続管理する。
 *       サーバー再起動後も監査ログが保持される。
 *
 * 設計原則:
 *   - シングルトン export でアプリ全体共有（本番用）
 *   - クラスも export してテストで ':memory:' インスタンスを生成可能
 *   - getById / list はコピーを返す（外部変更がストア内部に影響しない）
 *   - list は timestamp 降順（最新順）で返す
 *   - better-sqlite3 は同期 API: Next.js Route Handlers から安全に使える
 *
 * 後方互換性:
 *   - インタフェース（append / getById / list / clear / size）は変更なし
 *   - AuditStore インターフェース実装を維持
 */

import type Database from 'better-sqlite3';
import type { AuditRecord, AuditStore } from '@/types/audit_trail';
import { openDatabase, resolveDbPath } from '@/lib/db';

// ─── AuditTrailStore クラス ───────────────────────────────────────────────────

/**
 * 監査証跡を管理する SQLite 永続化ストア。
 * クラスを export することでテストが ':memory:' インスタンスを生成できる。
 */
export class AuditTrailStore implements AuditStore {
  private db: Database.Database;
  private stmtInsert: Database.Statement;
  private stmtSelectById: Database.Statement;
  private stmtSelectAll: Database.Statement;
  private stmtSelectLimit: Database.Statement;
  private stmtCount: Database.Statement;

  /**
   * @param dbPath SQLite ファイルパス。':memory:' でインメモリDB（テスト用）。
   *               省略時は ':memory:'（テスト互換のデフォルト）。
   *               本番シングルトンは resolveDbPath() を明示的に渡す。
   */
  constructor(dbPath: string = ':memory:') {
    this.db = openDatabase(dbPath);

    // プリペアドステートメント（パフォーマンス最適化 + SQLインジェクション防止）
    this.stmtInsert = this.db.prepare(`
      INSERT OR REPLACE INTO audit_trail (
        audit_trail_id, request_id, timestamp, pdf_filename,
        line_items_count, tax_verdict, practice_verdict, final_verdict,
        confidence, account_category, useful_life, elapsed_ms, model_used
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);

    this.stmtSelectById = this.db.prepare(
      `SELECT * FROM audit_trail WHERE audit_trail_id = ?`,
    );

    this.stmtSelectAll = this.db.prepare(
      `SELECT * FROM audit_trail ORDER BY timestamp DESC, rowid DESC`,
    );

    this.stmtSelectLimit = this.db.prepare(
      `SELECT * FROM audit_trail ORDER BY timestamp DESC, rowid DESC LIMIT ?`,
    );

    this.stmtCount = this.db.prepare(`SELECT COUNT(*) as cnt FROM audit_trail`);
  }

  /**
   * レコードを追加する（既存 audit_trail_id は上書き: INSERT OR REPLACE）。
   */
  append(record: AuditRecord): void {
    this.stmtInsert.run(
      record.audit_trail_id,
      record.request_id,
      record.timestamp,
      record.pdf_filename,
      record.line_items_count,
      record.tax_verdict,
      record.practice_verdict,
      record.final_verdict,
      record.confidence,
      record.account_category ?? null,
      record.useful_life ?? null,
      record.elapsed_ms,
      record.model_used,
    );
  }

  /**
   * audit_trail_id でレコードを取得する。
   * 見つからない場合は null を返す。
   */
  getById(id: string): AuditRecord | null {
    const row = this.stmtSelectById.get(id) as AuditRecord | undefined;
    if (!row) return null;
    return this.rowToRecord(row);
  }

  /**
   * 最新順（timestamp DESC）でレコードを取得する（limit 省略時は全件）。
   */
  list(limit?: number): AuditRecord[] {
    const rows = (
      limit !== undefined
        ? this.stmtSelectLimit.all(limit)
        : this.stmtSelectAll.all()
    ) as AuditRecord[];
    return rows.map((r) => this.rowToRecord(r));
  }

  /**
   * ストアをリセットする（全件削除）。
   * テスト用途 / 再起動シミュレーション。
   */
  clear(): void {
    this.db.prepare(`DELETE FROM audit_trail`).run();
  }

  /** 登録済み件数を返す。 */
  size(): number {
    const row = this.stmtCount.get() as { cnt: number };
    return row.cnt;
  }

  /** DB接続を閉じる（テスト後のクリーンアップ用）。 */
  close(): void {
    this.db.close();
  }

  /** SQLite 行 → AuditRecord 変換（null 型の正規化）。 */
  private rowToRecord(row: AuditRecord): AuditRecord {
    return {
      audit_trail_id: row.audit_trail_id,
      request_id: row.request_id,
      timestamp: row.timestamp,
      pdf_filename: row.pdf_filename,
      line_items_count: row.line_items_count,
      tax_verdict: row.tax_verdict,
      practice_verdict: row.practice_verdict,
      final_verdict: row.final_verdict,
      confidence: row.confidence,
      account_category: row.account_category ?? null,
      useful_life: row.useful_life ?? null,
      elapsed_ms: row.elapsed_ms,
      model_used: row.model_used,
    };
  }
}

// ─── シングルトン ─────────────────────────────────────────────────────────────

/**
 * アプリケーション全体で共有するシングルトンインスタンス（本番用）。
 * route.ts から参照する。
 *
 * DB パスは SQLITE_DB_PATH 環境変数 または resolveDbPath() で解決される。
 */
export const auditStore = new AuditTrailStore(resolveDbPath());
