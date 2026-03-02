/**
 * AuditTrailStore: 監査証跡 インメモリ永続化ストア（MVP）
 * 根拠: DESIGN_PDF_FIRST_MULTI_AGENT_VER2.md Phase 2 Audit Trail基盤
 *
 * 役割: classify_pdf の判定結果を記録し、GET /api/v2/audit_trail/:id で取得可能にする。
 *       Phase 2 MVP はインメモリ（シングルトン）。
 *       将来的に DB / Redis 等に差し替え可能な設計（AuditStore インターフェース経由）。
 *
 * 設計原則:
 *   - シングルトン export でアプリ全体共有
 *   - クラスも export してテストで新鮮なインスタンスを生成可能
 *   - getById / list はコピーを返す（外部変更がストア内部に影響しない）
 *   - list は挿入の逆順（最新順）で返す
 */

import type { AuditRecord, AuditStore } from '@/types/audit_trail';

// ─── AuditTrailStore クラス ───────────────────────────────────────────────────

/**
 * 監査証跡を管理するインメモリストア。
 * クラスを export することでテストが fresh インスタンスを生成できる。
 */
export class AuditTrailStore implements AuditStore {
  /** audit_trail_id → AuditRecord のマップ */
  private records: Map<string, AuditRecord> = new Map();

  /**
   * レコードを追加する（既存 ID は上書き）。
   * 内部マップにはコピーを格納（外部変更からの保護）。
   */
  append(record: AuditRecord): void {
    this.records.set(record.audit_trail_id, { ...record });
  }

  /**
   * audit_trail_id でレコードを取得する。
   * 見つからない場合は null を返す。
   */
  getById(id: string): AuditRecord | null {
    const record = this.records.get(id);
    return record ? { ...record } : null;
  }

  /**
   * 最新順でレコードを取得する（limit 省略時は全件）。
   * Map は挿入順を保持するため、逆順 = 最新順になる。
   */
  list(limit?: number): AuditRecord[] {
    const all = Array.from(this.records.values())
      .map((r) => ({ ...r }))
      .reverse();
    return limit !== undefined ? all.slice(0, limit) : all;
  }

  /**
   * ストアをリセットする。
   * テスト用途 / 再起動シミュレーション。
   */
  clear(): void {
    this.records.clear();
  }

  /** 登録済み件数を返す。 */
  size(): number {
    return this.records.size;
  }
}

// ─── シングルトン ─────────────────────────────────────────────────────────────

/**
 * アプリケーション全体で共有するシングルトンインスタンス。
 * route.ts から参照する。
 *
 * 将来の拡張点: DB / Redis 永続化への置換はこの export を差し替えるだけで済む。
 */
export const auditStore = new AuditTrailStore();
