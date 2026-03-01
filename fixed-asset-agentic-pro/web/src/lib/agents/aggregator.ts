/**
 * Aggregator: 合議判定
 * 根拠: DESIGN_PDF_FIRST_MULTI_AGENT_VER2.md Section 3.5
 *
 * 純 TypeScript 実装（外部 API 不要）。
 * Tax Agent + Practice Agent の各明細判定を受け取り、
 * 設計書の 8 パターン合議ルールで最終 verdict と信頼度を算出する。
 */

import type {
  TaxAgentResult,
  PracticeAgentResult,
  AggregatedResult,
  AgentVerdict,
  FinalVerdict,
} from '@/types/multi_agent';

// ─── 合議ルールテーブル ──────────────────────────────────────────────────────

interface AggregateRule {
  final_verdict: FinalVerdict;
  confidence: number;
}

/**
 * 2 エージェントの verdict を受け取り合議ルールを返す。
 * 根拠: Section 3.5 合議ルール表（8 パターン）
 *
 * 手計算検証（CHECK-7b）:
 *   パターン1/2（全員一致）: confidence 0.95
 *   パターン3〜6（片方 UNCERTAIN）: confidence 0.80
 *   パターン7（分裂 CAPITAL vs EXPENSE）: GUIDANCE, confidence 0.50
 *   パターン8（両方 UNCERTAIN）: GUIDANCE, confidence 0.30
 *   ※対称ケース（EXPENSE vs CAPITAL）は #7 と同一扱い
 */
function getAggregateRule(tax: AgentVerdict, practice: AgentVerdict): AggregateRule {
  // パターン1: Tax:CAPITAL + Practice:CAPITAL → CAPITAL_LIKE, 0.95（Section 3.5 #1）
  if (tax === 'CAPITAL' && practice === 'CAPITAL') {
    return { final_verdict: 'CAPITAL_LIKE', confidence: 0.95 };
  }
  // パターン2: Tax:EXPENSE + Practice:EXPENSE → EXPENSE_LIKE, 0.95（Section 3.5 #2）
  if (tax === 'EXPENSE' && practice === 'EXPENSE') {
    return { final_verdict: 'EXPENSE_LIKE', confidence: 0.95 };
  }
  // パターン3: Tax:CAPITAL + Practice:UNCERTAIN → CAPITAL_LIKE, 0.80（Section 3.5 #3）
  if (tax === 'CAPITAL' && practice === 'UNCERTAIN') {
    return { final_verdict: 'CAPITAL_LIKE', confidence: 0.80 };
  }
  // パターン4: Tax:UNCERTAIN + Practice:CAPITAL → CAPITAL_LIKE, 0.80（Section 3.5 #4）
  if (tax === 'UNCERTAIN' && practice === 'CAPITAL') {
    return { final_verdict: 'CAPITAL_LIKE', confidence: 0.80 };
  }
  // パターン5: Tax:EXPENSE + Practice:UNCERTAIN → EXPENSE_LIKE, 0.80（Section 3.5 #5）
  if (tax === 'EXPENSE' && practice === 'UNCERTAIN') {
    return { final_verdict: 'EXPENSE_LIKE', confidence: 0.80 };
  }
  // パターン6: Tax:UNCERTAIN + Practice:EXPENSE → EXPENSE_LIKE, 0.80（Section 3.5 #6）
  if (tax === 'UNCERTAIN' && practice === 'EXPENSE') {
    return { final_verdict: 'EXPENSE_LIKE', confidence: 0.80 };
  }
  // パターン7/対称: CAPITAL vs EXPENSE（分裂）→ GUIDANCE, 0.50（Section 3.5 #7）
  if (
    (tax === 'CAPITAL' && practice === 'EXPENSE') ||
    (tax === 'EXPENSE' && practice === 'CAPITAL')
  ) {
    return { final_verdict: 'GUIDANCE', confidence: 0.50 };
  }
  // パターン8: Tax:UNCERTAIN + Practice:UNCERTAIN → GUIDANCE, 0.30（Section 3.5 #8）
  return { final_verdict: 'GUIDANCE', confidence: 0.30 };
}

// ─── メイン関数 ──────────────────────────────────────────────────────────────

/**
 * 合議判定を実行する。
 *
 * @param taxResults      Tax Agent の出力。null の場合は Agent 失敗（全明細を UNCERTAIN 扱い）
 * @param practiceResults Practice Agent の出力。null の場合は Agent 失敗（全明細を UNCERTAIN 扱い）
 * @returns AggregatedResult[]（taxResults の line_item_id 順を保ち、Practice のみに存在する ID を末尾に追加）
 *
 * エラー耐性（根拠: Section 6 エラーハンドリング）:
 *   - 片方の Agent が失敗（null）した場合、失敗側を UNCERTAIN とみなして合議ルールを適用する
 *   - 両方が null の場合は空配列を返す
 */
export function aggregate(
  taxResults: TaxAgentResult[] | null,
  practiceResults: PracticeAgentResult[] | null,
): AggregatedResult[] {
  const taxArr = taxResults ?? [];
  const practiceArr = practiceResults ?? [];

  const taxMap = new Map(taxArr.map((r) => [r.line_item_id, r]));
  const practiceMap = new Map(practiceArr.map((r) => [r.line_item_id, r]));

  // Tax の順序を保ちつつ、Practice のみに存在する ID を末尾に追加
  const allIds: string[] = [
    ...taxArr.map((r) => r.line_item_id),
    ...practiceArr
      .filter((r) => !taxMap.has(r.line_item_id))
      .map((r) => r.line_item_id),
  ];

  if (allIds.length === 0) return [];

  return allIds.map((line_item_id) => {
    const tax = taxMap.get(line_item_id) ?? null;
    const practice = practiceMap.get(line_item_id) ?? null;

    const taxVerdict: AgentVerdict = tax?.verdict ?? 'UNCERTAIN';
    const practiceVerdict: AgentVerdict = practice?.verdict ?? 'UNCERTAIN';

    const rule = getAggregateRule(taxVerdict, practiceVerdict);

    // 勘定科目: Tax 優先（根拠: Section 3.5 勘定科目の合議ルール）
    const account_category =
      tax?.account_category != null
        ? tax.account_category
        : (practice?.suggested_account ?? null);

    // 耐用年数: Tax Agent の値を正とする（根拠: Section 3.5）
    const useful_life = tax?.useful_life ?? null;

    // 勘定科目一致ボーナス: +0.05（根拠: Section 3.5 勘定科目一致時の信頼度加算）
    // 手計算検算（CHECK-7b）:
    //   P1(CAPITAL+CAPITAL, 勘定科目一致) → 0.95 + 0.05 = 1.0（上限クランプ）
    //   P3(CAPITAL+UNCERTAIN, 勘定科目一致) → 0.80 + 0.05 = 0.85
    //   片方 null の場合は比較不可のため加算なし
    const accountCategoryMatch =
      tax?.account_category != null &&
      practice?.suggested_account != null &&
      tax.account_category === practice.suggested_account;
    const confidence = accountCategoryMatch
      ? Math.round(Math.min(rule.confidence + 0.05, 1.0) * 100) / 100
      : rule.confidence;

    // 分裂時の理由（両者が明確に対立している場合のみ設定）
    let disagreement_reason: string | undefined;
    if (
      rule.final_verdict === 'GUIDANCE' &&
      taxVerdict !== 'UNCERTAIN' &&
      practiceVerdict !== 'UNCERTAIN' &&
      taxVerdict !== practiceVerdict
    ) {
      disagreement_reason = `Tax: ${taxVerdict} / Practice: ${practiceVerdict} — 判定分裂`;
    }

    return {
      line_item_id,
      final_verdict: rule.final_verdict,
      confidence,
      account_category,
      useful_life,
      tax_result: tax,
      practice_result: practice,
      ...(disagreement_reason !== undefined ? { disagreement_reason } : {}),
    };
  });
}
