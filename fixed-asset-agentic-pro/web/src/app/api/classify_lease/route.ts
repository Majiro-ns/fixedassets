import { NextRequest, NextResponse } from 'next/server';
import type { LeaseClassifyRequest, LeaseClassifyResponse } from '@/types/classify_lease';

// ─── IFRS 16 計算ロジック ──────────────────────────────────────────────────

/**
 * 短期リース判定（IFRS 16 § B34）
 * termMonths <= 12 かつ購入オプション確実行使なし
 */
function isShortTermLease(termMonths: number, hasPurchaseOptionCertain: boolean): boolean {
  return termMonths <= 12 && !hasPurchaseOptionCertain;
}

/**
 * 少額資産判定（IFRS 16 § B3-B8）
 * 原資産新品時公正価値 <= USD 5,000（BC100準拠）
 */
function isLowValueAsset(assetNewValueUsd: number): boolean {
  return assetNewValueUsd <= 5000;
}

/**
 * リース負債（初期測定）計算（IFRS 16 § 26-28）
 * PV = PMT × [(1 - (1+r)^(-n)) / r]
 *
 * 月利率算出方法: 簡便法（年率÷12）採用（IFRS 16§28, IFRS準拠として許容。家老壱決定 2026-03-01）
 * 厳密法(1+r)^(1/12)-1との差: 本テストケースで¥2,110（0.06%）= 重要性なし
 *
 * 検証: PMT=100000, n=36, r=0.0025 → Math.round(100000 × 34.3864) = 3,438,640 ✓
 */
function calcLeaseLiability(
  monthlyPayment: number,
  termMonths: number,
  annualIbr: number,
): number {
  if (annualIbr === 0) {
    return monthlyPayment * termMonths;  // 金利ゼロの特殊ケース
  }
  const r = annualIbr / 12;  // 月次割引率（簡便法）
  const pv = monthlyPayment * (1 - Math.pow(1 + r, -termMonths)) / r;
  return Math.round(pv);
}

/**
 * ROU資産（使用権資産）初期測定（IFRS 16 § 24-25）
 * ROU = リース負債 + 当初直接費用 + 前払 + 原状回復費用 - インセンティブ
 */
function calcRouAsset(
  leaseLiability: number,
  initialDirectCosts = 0,
  prepaid = 0,
  restoration = 0,
  incentives = 0,
): number {
  return leaseLiability + initialDirectCosts + prepaid + restoration - incentives;
}

// ─── 定数 ─────────────────────────────────────────────────────────────────

const DISCLAIMER =
  'この計算は IFRS 16 Leases（2016年版）に基づく参考値です。' +
  'IBRの見積もりは専門家に確認し、適用基準（IFRS/J-GAAP）を必ず確認してください。';

// ─── POSTハンドラ ─────────────────────────────────────────────────────────

export async function POST(req: NextRequest): Promise<NextResponse<LeaseClassifyResponse>> {
  let body: LeaseClassifyRequest;
  try {
    body = (await req.json()) as LeaseClassifyRequest;
  } catch {
    return NextResponse.json(
      {
        decision: 'GUIDANCE',
        lease_type: 'QUALIFYING_LEASE',
        is_short_term: false,
        is_low_value: false,
        reasons: ['リクエストのパースに失敗しました'],
        confidence: 0,
        missing_fields: [],
        disclaimer: DISCLAIMER,
      } satisfies LeaseClassifyResponse,
      { status: 400 },
    );
  }

  const {
    is_substitution_right_substantive,
    contract_term_months,
    monthly_payment,
    asset_new_value_usd,
    has_purchase_option_certain = false,
    annual_ibr,
    initial_direct_costs = 0,
    prepaid_lease_payments = 0,
    restoration_cost_estimate = 0,
    lease_incentives_received = 0,
  } = body;

  // ─── Step 1: リース識別（供給者代替権判定）────────────────────────────────
  // is_substitution_right_substantive が true → NOT_A_LEASE
  if (is_substitution_right_substantive === true) {
    return NextResponse.json({
      decision: 'EXPENSE_LIKE',
      lease_type: 'NOT_A_LEASE',
      is_short_term: false,
      is_low_value: false,
      reasons: [
        '供給者の実質的代替権あり → リースとして識別されません（IFRS 16 § B14）',
        '費用処理を適用します',
      ],
      confidence: 0.9,
      missing_fields: [],
      disclaimer: DISCLAIMER,
    } satisfies LeaseClassifyResponse);
  }

  // ─── Step 2: 免除判定 ────────────────────────────────────────────────────
  const shortTerm = isShortTermLease(contract_term_months, has_purchase_option_certain);
  const lowValue =
    asset_new_value_usd !== undefined ? isLowValueAsset(asset_new_value_usd) : false;

  if (shortTerm) {
    return NextResponse.json({
      decision: 'EXPENSE_LIKE',
      lease_type: 'EXEMPT_SHORT_TERM',
      is_short_term: true,
      is_low_value: lowValue,
      reasons: [
        `リース期間 ${contract_term_months} ヶ月 ≤ 12 ヶ月 → 短期リース免除（IFRS 16 § B34）`,
        '費用として定額認識します',
      ],
      confidence: 0.9,
      missing_fields: [],
      disclaimer: DISCLAIMER,
    } satisfies LeaseClassifyResponse);
  }

  if (lowValue) {
    return NextResponse.json({
      decision: 'EXPENSE_LIKE',
      lease_type: 'EXEMPT_LOW_VALUE',
      is_short_term: false,
      is_low_value: true,
      reasons: [
        `原資産新品価値 USD ${asset_new_value_usd} ≤ USD 5,000 → 少額資産免除（IFRS 16 § B3-B8）`,
        '費用として定額認識します',
      ],
      confidence: 0.9,
      missing_fields: [],
      disclaimer: DISCLAIMER,
    } satisfies LeaseClassifyResponse);
  }

  // ─── Step 3: QUALIFYING_LEASE 計算 ──────────────────────────────────────
  // annual_ibr 未入力 → GUIDANCE（入力誘導）
  if (annual_ibr === undefined || annual_ibr === null) {
    return NextResponse.json({
      decision: 'GUIDANCE',
      lease_type: 'QUALIFYING_LEASE',
      is_short_term: false,
      is_low_value: false,
      reasons: [
        '認識対象リース（IFRS 16 § 22）です。',
        'リース負債計算には追加借入利子率（IBR）の入力が必要です',
      ],
      confidence: 0.7,
      missing_fields: ['annual_ibr'],
      disclaimer: DISCLAIMER,
    } satisfies LeaseClassifyResponse);
  }

  // annual_ibr あり → 計算実行
  const leaseLiability = calcLeaseLiability(monthly_payment, contract_term_months, annual_ibr);
  const rouAsset = calcRouAsset(
    leaseLiability,
    initial_direct_costs,
    prepaid_lease_payments,
    restoration_cost_estimate,
    lease_incentives_received,
  );

  return NextResponse.json({
    decision: 'CAPITAL_LIKE',
    lease_type: 'QUALIFYING_LEASE',
    is_short_term: false,
    is_low_value: false,
    lease_liability: leaseLiability,
    rou_asset: rouAsset,
    reasons: [
      `認識対象リース（IFRS 16 § 22）: ROU資産 ¥${rouAsset.toLocaleString()} を計上`,
      `リース負債（初期）: ¥${leaseLiability.toLocaleString()}（月利率 ${((annual_ibr / 12) * 100).toFixed(4)}% 簡便法）`,
      `月額 ¥${monthly_payment.toLocaleString()} × ${contract_term_months}ヶ月、IBR年率 ${(annual_ibr * 100).toFixed(2)}%`,
    ],
    confidence: 0.85,
    missing_fields: [],
    disclaimer: DISCLAIMER,
  } satisfies LeaseClassifyResponse);
}
