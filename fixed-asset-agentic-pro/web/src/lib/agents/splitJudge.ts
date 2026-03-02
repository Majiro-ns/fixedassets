/**
 * Split Judge: 分割判定エージェント（F-N09）
 * 根拠: 00_Requirements_Definition.md / cmd_170k_sub1 タスク仕様
 *
 * 一体資産 vs 分割計上の自動判定をルールベースで行う（LLM不要）。
 * 例: 「パソコン+モニター+キーボード 35万円」→ 一体資産(bundled)か個別3件(split)か
 *
 * 将来的にLLM判定へ切り替え可能な設計（interface分離）。
 *
 * CHECK-7: ドメイン知識根拠
 *   - 一体資産の判定基準: 法人税基本通達7-1-11（一括使用・一体機能）
 *   - 少額判定基準: 10万円未満（法人税法施行令第133条）
 *   - セット資産: 実務上「一体として機能する場合は合計額で判定」
 *
 * CHECK-7b 手計算検証:
 *   入力: PC 20万 + モニター 8万 + キーボード 2万 = 合計30万
 *   → 個別は全て30万未満だがPC+モニターは物理的不可分 → bundled（合計30万で判定）
 */

import type { ExtractedLineItem, ExtractedLineItems } from '@/types/classify_pdf_v2';
import type { SplitGroup, SplitJudgeResult } from '@/types/split_judge';

// ─── ルールベース判定の定数 ───────────────────────────────────────────────

/**
 * 「一体資産」を示すキーワード（品名・説明に含まれる場合は bundled 判定）
 * 根拠: 実務上「セット」「一式」「一体」は合計額で固定資産判定する慣行
 */
const BUNDLE_KEYWORDS = [
  'セット',
  '一式',
  '一体',
  'set',
  'suite',
  'パッケージ',
  'システム一式',
  '機器一式',
  '設備一式',
];

/**
 * 物理的に分離不可能な機器ペアグループ
 * 根拠: 法基通7-1-11「資産の効用を発揮するために一体として使用される場合」
 *
 * 各サブ配列が「同一グループ」。2つ以上のキーワードが同一購入に含まれる場合 bundled。
 */
const INSEPARABLE_GROUPS: readonly string[][] = [
  ['pc', 'パソコン', 'ノートpc', 'デスクトップ', '本体', 'コンピュータ'],  // PC本体
  ['モニター', 'ディスプレイ', 'monitor', 'display'],                       // ディスプレイ
  ['キーボード', 'keyboard'],                                                // キーボード
  ['マウス', 'mouse', 'ポインティングデバイス'],                             // マウス
  ['ラック', 'サーバーラック', 'rack'],                                      // サーバーラック
] as const;

/** 個別明細の少額基準（この金額未満の明細は単独では費用処理可能） */
const SMALL_AMOUNT_THRESHOLD = 100_000; // 10万円

/** グループ合計がこの金額を超える場合は「一体資産として要判定」 */
const BUNDLE_TOTAL_THRESHOLD = 300_000; // 30万円

// ─── インターフェース（LLM切り替え用） ────────────────────────────────────

/**
 * SplitJudge の処理インターフェース
 * 将来: runSplitJudge を LLM実装に差し替えても呼び出し側は変更不要
 */
export interface ISplitJudge {
  judge(extracted: ExtractedLineItems): SplitJudgeResult;
}

// ─── ルールベース実装 ────────────────────────────────────────────────────

/**
 * キーワードを含むかチェック（大文字小文字・全角半角を正規化して比較）
 */
function containsKeyword(text: string, keywords: readonly string[]): boolean {
  const normalized = text.toLowerCase().replace(/\s+/g, '');
  return keywords.some((kw) => normalized.includes(kw.toLowerCase()));
}

/**
 * ルール1: バンドルキーワード判定
 * 品名に「セット」「一式」等が含まれる → bundled
 */
function applyBundleKeywordRule(items: ExtractedLineItem[]): string | null {
  for (const item of items) {
    if (containsKeyword(item.description, BUNDLE_KEYWORDS)) {
      const matched = BUNDLE_KEYWORDS.find((kw) =>
        item.description.toLowerCase().includes(kw.toLowerCase())
      );
      return `品名に「${matched}」を含む（一体資産として判定）`;
    }
  }
  return null;
}

/**
 * ルール2: 物理的不可分ペア判定
 * PC + モニター、PC + キーボード 等の組み合わせ → bundled
 *
 * CHECK-7b: 「パソコン」「モニター」が同一グループに存在 → 物理的不可分と判定
 */
function applyInseparablePairRule(items: ExtractedLineItem[]): string | null {
  if (items.length < 2) return null;

  // 各明細がどのグループに属するかをマッピング
  const groupHits = new Set<number>();
  for (const item of items) {
    for (let gi = 0; gi < INSEPARABLE_GROUPS.length; gi++) {
      if (containsKeyword(item.description, INSEPARABLE_GROUPS[gi])) {
        groupHits.add(gi);
      }
    }
  }

  // PC本体(group 0) + 周辺機器(group 1,2,3) の組み合わせがある場合
  const hasPcBody = groupHits.has(0);
  const hasPeripheral = groupHits.has(1) || groupHits.has(2) || groupHits.has(3);

  if (hasPcBody && hasPeripheral) {
    const peripheralNames = items
      .filter((item) =>
        INSEPARABLE_GROUPS.slice(1, 4).some((g) => containsKeyword(item.description, g))
      )
      .map((item) => item.description)
      .join('・');
    return `物理的不可分な組み合わせ（PC本体と${peripheralNames}）`;
  }

  return null;
}

/**
 * ルール3: 少額合算判定
 * 個別明細が全て10万円未満 かつ グループ合計が30万円超 → bundled
 *
 * CHECK-7b: 個別8万円×4台 = 32万円 → 個別は全て少額だが合計は固定資産として要判定
 */
function applySmallAmountAggregationRule(items: ExtractedLineItem[]): string | null {
  if (items.length < 2) return null;

  const allSmall = items.every((item) => item.amount < SMALL_AMOUNT_THRESHOLD);
  const total = items.reduce((sum, item) => sum + item.amount, 0);

  if (allSmall && total > BUNDLE_TOTAL_THRESHOLD) {
    return `個別明細は全て${(SMALL_AMOUNT_THRESHOLD / 10000).toFixed(0)}万円未満だが合計${(total / 10000).toFixed(0)}万円が${(BUNDLE_TOTAL_THRESHOLD / 10000).toFixed(0)}万円超（合計額で固定資産判定が必要）`;
  }

  return null;
}

/**
 * 明細グループに対してルールを適用し、SplitGroup を返す
 */
function judgeGroup(items: ExtractedLineItem[]): SplitGroup {
  const groupTotal = items.reduce((sum, item) => sum + item.amount, 0);

  // ルール1: バンドルキーワード
  const keywordReason = applyBundleKeywordRule(items);
  if (keywordReason) {
    return { items, judgment: 'bundled', reason: keywordReason, group_total: groupTotal };
  }

  // ルール2: 物理的不可分ペア
  const inseparableReason = applyInseparablePairRule(items);
  if (inseparableReason) {
    return { items, judgment: 'bundled', reason: inseparableReason, group_total: groupTotal };
  }

  // ルール3: 少額合算
  const aggregationReason = applySmallAmountAggregationRule(items);
  if (aggregationReason) {
    return { items, judgment: 'bundled', reason: aggregationReason, group_total: groupTotal };
  }

  // 上記ルールに該当しない → 個別計上
  if (items.length === 1) {
    return {
      items,
      judgment: 'split',
      reason: '単一明細のため個別計上',
      group_total: groupTotal,
    };
  }

  return {
    items,
    judgment: 'split',
    reason: '一体資産の要件に該当しないため個別計上',
    group_total: groupTotal,
  };
}

// ─── メイン関数 ──────────────────────────────────────────────────────────

/**
 * 分割判定を実行する（ルールベース実装）。
 *
 * 同一文書（同一購入日・同一業者）の明細を入力として受け取り、
 * 一体資産(bundled) か 個別計上(split) かを判定する。
 *
 * @param extracted  PDF抽出結果（document_date + vendor + items）
 * @returns SplitJudgeResult
 *
 * @example
 * // PC一式（PC本体+モニター+キーボード）→ bundled
 * runSplitJudge({
 *   items: [
 *     { line_item_id: 'li_1', description: 'ノートPC', amount: 200000 },
 *     { line_item_id: 'li_2', description: 'モニター', amount: 80000 },
 *     { line_item_id: 'li_3', description: 'キーボード', amount: 20000 },
 *   ]
 * })
 * // → { groups: [{ items: [全3件], judgment: 'bundled', reason: '物理的不可分...', group_total: 300000 }] }
 */
export function runSplitJudge(extracted: ExtractedLineItems): SplitJudgeResult {
  const items = extracted.items ?? [];

  // 空配列のエッジケース
  if (items.length === 0) {
    return { groups: [] };
  }

  // 単一明細のエッジケース
  if (items.length === 1) {
    return {
      groups: [
        {
          items,
          judgment: 'split',
          reason: '単一明細のため個別計上',
          group_total: items[0].amount,
        },
      ],
    };
  }

  // 複数明細: まず全体を一つのグループとして評価
  // （同一文書 = 同一購入日・同一業者前提）
  const bundleGroup = judgeGroup(items);
  if (bundleGroup.judgment === 'bundled') {
    return { groups: [bundleGroup] };
  }

  // bundled でなければ各明細を個別グループとして返す
  const splitGroups: SplitGroup[] = items.map((item) => ({
    items: [item],
    judgment: 'split' as const,
    reason: '個別計上',
    group_total: item.amount,
  }));

  return { groups: splitGroups };
}
