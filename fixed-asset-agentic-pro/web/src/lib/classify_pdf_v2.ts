/**
 * /v2/classify_pdf クライアント関数 + 変換ユーティリティ
 * 根拠: 設計書 Section 5.2（API仕様）/ Section 12（Feature Flag）
 *
 * 注意: classifyFromPDFv2() は /api/v2/classify_pdf に依存する。
 *       API ルート（route.ts）は足軽8が実装中 — Phase 1-B 完成後に有効化。
 */

import type { ClassifyPDFV2Request, ClassifyPDFV2Response } from '@/types/classify_pdf_v2';
import type { LineItemWithAction } from '@/types/pdf_review';

// ─── Feature Flag ──────────────────────────────────────────────────────────

/**
 * USE_MULTI_AGENT フラグを返す。
 * 根拠: Section 12 — デフォルトは false（初回リリース後 true に段階切替）
 */
export function getUseMultiAgent(): boolean {
  return process.env.NEXT_PUBLIC_USE_MULTI_AGENT === 'true';
}

// ─── Base64 変換ユーティリティ ─────────────────────────────────────────────

/** File → base64 文字列 */
export async function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      // "data:application/pdf;base64,XXXX" → "XXXX"
      const base64 = result.split(',')[1] ?? '';
      resolve(base64);
    };
    reader.onerror = () => reject(new Error('FileReader エラー'));
    reader.readAsDataURL(file);
  });
}

// ─── v2 API クライアント ───────────────────────────────────────────────────

/**
 * POST /api/v2/classify_pdf を呼び出す。
 * 根拠: Section 5.2 リクエスト仕様
 *
 * [Phase 1-B 完成後に PDFUploadCard から呼び出す]
 */
export async function classifyFromPDFv2(
  file: File,
  options?: {
    company_id?: string | null;
    include_audit_trail?: boolean;
    parallel_agents?: boolean;
  },
): Promise<ClassifyPDFV2Response> {
  const base64 = await fileToBase64(file);

  const payload: ClassifyPDFV2Request = {
    pdf_base64: base64,
    company_id: options?.company_id ?? null,
    options: {
      include_audit_trail: options?.include_audit_trail ?? true,
      parallel_agents: options?.parallel_agents ?? true,
    },
  };

  const res = await fetch('/api/v2/classify_pdf', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API v2 error ${res.status}: ${text}`);
  }

  return res.json() as Promise<ClassifyPDFV2Response>;
}

// ─── 変換ユーティリティ ────────────────────────────────────────────────────

/**
 * ClassifyPDFV2Response → LineItemWithAction[] に変換する。
 * 根拠: Section 5.2 line_results + Section 1.2 判定値用語対応
 *
 * extraction_failed の場合は空配列を返す（UI は手入力へ誘導）。
 */
export function convertV2ToLineItems(response: ClassifyPDFV2Response): LineItemWithAction[] {
  if (response.status === 'extraction_failed' || !response.extracted) {
    return [];
  }

  const itemMap = new Map(
    response.extracted.items.map((item) => [item.line_item_id, item]),
  );

  return response.line_results.map((lr) => {
    const extracted = itemMap.get(lr.line_item_id);
    return {
      id: lr.line_item_id,
      description: extracted?.description ?? '',
      amount: extracted?.amount,
      verdict: lr.verdict,
      confidence: lr.confidence,
      rationale: lr.tax_rationale,
      userAction: 'pending' as const,
      finalVerdict: lr.verdict,
    };
  });
}
