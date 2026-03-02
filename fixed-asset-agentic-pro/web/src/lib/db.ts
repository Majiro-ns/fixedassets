/**
 * SQLite 接続ユーティリティ
 * 根拠: cmd_160k_sub2 Store永続化 — TrainingDataStore / AuditTrailStore の永続化基盤
 *
 * 設計原則:
 *   - better-sqlite3 は同期APIのため、Next.js Server Components / Route Handlers から安全に使える
 *   - dbPath: ':memory:' を渡すとインメモリDBを使用（テスト用途）
 *   - dbPath: ファイルパスを渡すとファイルDBを使用（本番用途）
 *   - テーブルは初回接続時に CREATE TABLE IF NOT EXISTS で自動作成
 */

import Database from 'better-sqlite3';
import path from 'path';
import fs from 'fs';

// ─── デフォルト DB パス ───────────────────────────────────────────────────────

/**
 * 本番用DBパスの解決。
 * 環境変数 SQLITE_DB_PATH が設定されていればそれを使う。
 * なければ プロジェクトルート/db/fixed-asset.db を使う。
 */
export function resolveDbPath(): string {
  if (process.env.SQLITE_DB_PATH) return process.env.SQLITE_DB_PATH;
  const root = path.resolve(process.cwd(), '..'); // web/ の親 = プロジェクトルート
  return path.join(root, 'db', 'fixed-asset.db');
}

// ─── DB 初期化 ────────────────────────────────────────────────────────────────

/**
 * SQLite データベースを開き、テーブルを作成して返す。
 *
 * @param dbPath ファイルパス or ':memory:'（省略時はresolveDbPath()を使用）
 */
export function openDatabase(dbPath?: string): Database.Database {
  const resolvedPath = dbPath ?? resolveDbPath();

  // ファイルDBの場合はディレクトリを作成
  if (resolvedPath !== ':memory:') {
    const dir = path.dirname(resolvedPath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
  }

  const db = new Database(resolvedPath);

  // WAL モード: 読み取り/書き込みの並行性向上
  db.pragma('journal_mode = WAL');

  // ─── training_data テーブル ─────────────────────────────────────────────
  db.exec(`
    CREATE TABLE IF NOT EXISTS training_data (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      item        TEXT    NOT NULL,
      amount      REAL    NOT NULL,
      label       TEXT    NOT NULL CHECK(label IN ('固定資産', '費用', '要確認')),
      notes       TEXT,
      created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    )
  `);

  // ─── audit_trail テーブル ────────────────────────────────────────────────
  db.exec(`
    CREATE TABLE IF NOT EXISTS audit_trail (
      audit_trail_id    TEXT  PRIMARY KEY,
      request_id        TEXT  NOT NULL,
      timestamp         TEXT  NOT NULL,
      pdf_filename      TEXT  NOT NULL,
      line_items_count  INTEGER NOT NULL,
      tax_verdict       TEXT  NOT NULL,
      practice_verdict  TEXT  NOT NULL,
      final_verdict     TEXT  NOT NULL,
      confidence        REAL  NOT NULL,
      account_category  TEXT,
      useful_life       INTEGER,
      elapsed_ms        INTEGER NOT NULL,
      model_used        TEXT  NOT NULL
    )
  `);

  return db;
}
