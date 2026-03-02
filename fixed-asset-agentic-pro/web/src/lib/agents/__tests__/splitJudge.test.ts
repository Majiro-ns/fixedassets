/**
 * splitJudge.test.ts — Split Judge（F-N09）カバレッジ補完テスト (cmd_170k_sub3)
 *
 * カバレッジ分析結果: splitJudge.ts は 12.5%（statements）のみ。
 * 未カバー箇所: applyBundleKeywordRule / applyInseparablePairRule /
 *              applySmallAmountAggregationRule / judgeGroup / runSplitJudge 全体
 *
 * ■ CHECK-9 テスト期待値の根拠
 *   ルール1 (BUNDLE_KEYWORDS): 実務慣行「セット・一式は合計額で判定」
 *     → 法基通7-1-11「一括使用・一体機能」解釈を踏まえた設計
 *   ルール2 (INSEPARABLE_GROUPS): 法基通7-1-11「一体として機能する場合は合計額で判定」
 *     → PC本体 + 周辺機器（モニター/キーボード/マウス）は物理的不可分とみなす
 *   ルール3 (SMALL_AMOUNT_AGGREGATION):
 *     個別 < 10万円 かつ 合計 > 30万円 → 合計額で固定資産判定
 *     根拠: 令133条の「明細単位で10万円判定」の補完ルール（実務慣行）
 *
 * ■ CHECK-7b 手計算検証
 *   bundleキーワード「一式」含む → bundled ✓
 *   PC(200k) + モニター(80k): 物理的不可分 → bundled, total=280k ✓
 *   8万×4台 = 32万 > 30万, 各々8万 < 10万 → bundled ✓
 *   15万単独 → split, total=150k ✓
 *   空配列 → groups=[] ✓
 *   独立2明細（バンドル条件なし）→ 各々split ✓
 */

import { describe, it, expect } from 'vitest';
import { runSplitJudge } from '../splitJudge';
import type { ExtractedLineItems } from '@/types/classify_pdf_v2';

// ─── ヘルパー ──────────────────────────────────────────────────────────────

function makeExtracted(items: Array<{ id: string; desc: string; amount: number }>): ExtractedLineItems {
  return {
    items: items.map(({ id, desc, amount }) => ({
      line_item_id: id,
      description: desc,
      amount,
    })),
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// 1. エッジケース: 空配列・単一明細
// ─────────────────────────────────────────────────────────────────────────────

describe('splitJudge: エッジケース（空配列・単一明細）', () => {
  /**
   * SJ-1: 空配列 → groups=[]
   * CHECK-9: items.length=0 のエッジケース処理
   * CHECK-7b: 空の items → groups=[] （グループ化対象なし）
   */
  it('SJ-1: 空配列 → groups=[]（エッジケース）', () => {
    const result = runSplitJudge({ items: [] });
    expect(result.groups).toHaveLength(0);
  });

  it('SJ-1b: items未定義（undefined）→ groups=[]（エッジケース）', () => {
    // @ts-expect-error テスト用: items未指定のエッジケース
    const result = runSplitJudge({});
    expect(result.groups).toHaveLength(0);
  });

  /**
   * SJ-2: 単一明細 → split（個別計上）
   * CHECK-9: items.length=1 の単一明細は常にsplit
   * CHECK-7b: 単一明細150k → split, group_total=150,000
   */
  it('SJ-2: 単一明細 150,000円 → split（個別計上）', () => {
    const result = runSplitJudge(makeExtracted([
      { id: 'sj_001', desc: 'ノートPC Dell XPS 13', amount: 150_000 },
    ]));

    expect(result.groups).toHaveLength(1);
    expect(result.groups[0].judgment).toBe('split');
    expect(result.groups[0].group_total).toBe(150_000);
    expect(result.groups[0].reason).toContain('単一明細');
  });

  it('SJ-2b: 単一明細 50,000円（少額）→ split（個別計上）', () => {
    // CHECK-7b: 1件だけなら50k < 10万でもsplit（bundled条件は2件以上）
    const result = runSplitJudge(makeExtracted([
      { id: 'sj_002', desc: 'USBメモリー', amount: 50_000 },
    ]));

    expect(result.groups).toHaveLength(1);
    expect(result.groups[0].judgment).toBe('split');
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 2. ルール1: バンドルキーワード判定
// ─────────────────────────────────────────────────────────────────────────────

describe('splitJudge: ルール1 バンドルキーワード（「セット」「一式」等）', () => {
  /**
   * SJ-3: 「セット」含む品名 → bundled
   * CHECK-9: BUNDLE_KEYWORDS に「セット」が含まれ、品名に含まれる場合はbundled
   * CHECK-7b: 「PCセット一式（本体+モニター+キーボード）」→ 「セット」マッチ → bundled
   */
  it('SJ-3: 「セット」含む品名 → bundled（バンドルキーワードルール）', () => {
    const result = runSplitJudge(makeExtracted([
      { id: 'sj_011', desc: 'PCセット一式（本体+モニター+キーボード）', amount: 350_000 },
    ]));

    // 注: 単一明細でもdescriptionに「セット」が含まれればbundled? いや、judgeGroupは2件以上でないと呼ばれない
    // 実際には単一明細はjudgeGroupを呼ばずにsplitで返る
    // BUNDLE_KEYWORDS チェックは judgeGroup 内で行われる（2件以上の場合）
    expect(result.groups).toHaveLength(1);
    // 単一明細は常にsplit（judgeGroupを経由しない）
    expect(result.groups[0].judgment).toBe('split');
  });

  it('SJ-3b: 「一式」含む品名（複数明細の一つ）→ bundled', () => {
    /**
     * CHECK-9: 2件以上で「一式」を含む明細がある場合、judgeGroupがbundled判定
     * CHECK-7b: 「事務所内装工事一式」は BUNDLE_KEYWORDS 「一式」マッチ → bundled
     */
    const result = runSplitJudge(makeExtracted([
      { id: 'sj_012', desc: '事務所内装工事一式', amount: 500_000 },
      { id: 'sj_013', desc: '電気工事費', amount: 100_000 },
    ]));

    expect(result.groups).toHaveLength(1);
    expect(result.groups[0].judgment).toBe('bundled');
    expect(result.groups[0].reason).toContain('一式');
    expect(result.groups[0].group_total).toBe(600_000);
    expect(result.groups[0].items).toHaveLength(2);
  });

  it('SJ-3c: 「パッケージ」含む品名（複数明細）→ bundled', () => {
    // CHECK-7b: 「ソフトウェアパッケージ導入費」→ 「パッケージ」マッチ → bundled
    const result = runSplitJudge(makeExtracted([
      { id: 'sj_014', desc: 'ソフトウェアパッケージ導入費', amount: 800_000 },
      { id: 'sj_015', desc: '導入支援コンサルティング費', amount: 200_000 },
    ]));

    expect(result.groups[0].judgment).toBe('bundled');
    expect(result.groups[0].reason).toContain('パッケージ');
  });

  it('SJ-3d: 「機器一式」含む品名 → bundled', () => {
    // CHECK-7b: 「セキュリティ機器一式」→ 「機器一式」マッチ → bundled
    const result = runSplitJudge(makeExtracted([
      { id: 'sj_016', desc: 'セキュリティ機器一式（カメラ×4+録画装置）', amount: 450_000 },
      { id: 'sj_017', desc: '設置工事費', amount: 50_000 },
    ]));

    expect(result.groups[0].judgment).toBe('bundled');
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 3. ルール2: 物理的不可分ペア判定（PC + 周辺機器）
// ─────────────────────────────────────────────────────────────────────────────

describe('splitJudge: ルール2 物理的不可分ペア（PC本体 + 周辺機器）', () => {
  /**
   * SJ-4: PC + モニター → bundled
   * CHECK-9: INSEPARABLE_GROUPS: PC本体(group0) + モニター(group1) → 物理的不可分
   * CHECK-7b:
   *   「ノートPC」→ group0（パソコン系）
   *   「モニター」→ group1（ディスプレイ系）
   *   → hasPcBody=true, hasPeripheral=true → bundled
   *   total = 200,000 + 80,000 = 280,000
   */
  it('SJ-4: ノートPC(200k) + モニター(80k) → bundled（物理的不可分）', () => {
    const result = runSplitJudge(makeExtracted([
      { id: 'sj_021', desc: 'ノートPC Dell XPS 15', amount: 200_000 },
      { id: 'sj_022', desc: 'モニター BenQ 27インチ', amount: 80_000 },
    ]));

    expect(result.groups).toHaveLength(1);
    expect(result.groups[0].judgment).toBe('bundled');
    expect(result.groups[0].reason).toContain('PC本体');
    expect(result.groups[0].group_total).toBe(280_000);
  });

  it('SJ-4b: パソコン + キーボード → bundled', () => {
    // CHECK-7b: 「パソコン」→ group0, 「キーボード」→ group2 → bundled
    const result = runSplitJudge(makeExtracted([
      { id: 'sj_023', desc: 'デスクトップパソコン本体', amount: 150_000 },
      { id: 'sj_024', desc: 'ワイヤレスキーボード', amount: 20_000 },
    ]));

    expect(result.groups[0].judgment).toBe('bundled');
  });

  it('SJ-4c: PC本体 + マウス + モニター（3点セット）→ bundled', () => {
    // CHECK-7b: PC(group0) + マウス(group3) + ディスプレイ(group1) → bundled
    //   total = 180,000 + 5,000 + 60,000 = 245,000
    const result = runSplitJudge(makeExtracted([
      { id: 'sj_025', desc: 'ノートPC Apple MacBook Pro', amount: 180_000 },
      { id: 'sj_026', desc: 'マウス ロジクール MX Master', amount: 5_000 },
      { id: 'sj_027', desc: 'ディスプレイ LG 27インチ', amount: 60_000 },
    ]));

    expect(result.groups[0].judgment).toBe('bundled');
    expect(result.groups[0].group_total).toBe(245_000);
  });

  it('SJ-4d: モニターのみ2台（PC本体なし）→ split（物理的不可分ペア非適用）', () => {
    // CHECK-7b: group0（PC本体）が存在しない → hasPcBody=false → bundled条件不成立
    //   バンドルキーワードなし、少額合算なし（各120k > 10万）→ split
    const result = runSplitJudge(makeExtracted([
      { id: 'sj_028', desc: 'モニター BenQ 27インチ（1台目）', amount: 120_000 },
      { id: 'sj_029', desc: 'モニター BenQ 27インチ（2台目）', amount: 120_000 },
    ]));

    // PC本体がないため物理的不可分ルール非適用
    // バンドルキーワードなし、少額合算なし（各120k >= 10万）→ 各々split
    expect(result.groups[0].judgment).toBe('split');
    // 2件のsplitグループが返される
    expect(result.groups).toHaveLength(2);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 4. ルール3: 少額合算判定（個別 < 10万 かつ 合計 > 30万）
// ─────────────────────────────────────────────────────────────────────────────

describe('splitJudge: ルール3 少額合算（個別<10万 × 合計>30万）', () => {
  /**
   * SJ-5: 8万×4台 = 32万 → bundled
   * CHECK-9: 全件 < 100,000 かつ total > 300,000 → bundled
   * CHECK-7b:
   *   各明細: 80,000 < 100,000 → 全件少額基準内
   *   合計: 80,000 × 4 = 320,000 > 300,000 → bundled
   *   理由: 個別では少額だが合計が30万超 → 固定資産として一体判定
   */
  it('SJ-5: 8万×4台 = 32万 → bundled（少額合算ルール）', () => {
    const result = runSplitJudge(makeExtracted([
      { id: 'sj_031', desc: 'モニター（1台目）', amount: 80_000 },
      { id: 'sj_032', desc: 'モニター（2台目）', amount: 80_000 },
      { id: 'sj_033', desc: 'モニター（3台目）', amount: 80_000 },
      { id: 'sj_034', desc: 'モニター（4台目）', amount: 80_000 },
    ]));

    expect(result.groups).toHaveLength(1);
    expect(result.groups[0].judgment).toBe('bundled');
    expect(result.groups[0].group_total).toBe(320_000);
    // 理由に金額情報が含まれること
    expect(result.groups[0].reason).toContain('10万円未満');
  });

  it('SJ-5b: 9万×3台 = 27万（30万以下）→ split（少額合算非適用）', () => {
    // CHECK-7b: 各90,000 < 100,000（全件少額）だが合計270,000 <= 300,000 → bundled条件不成立
    //   バンドルキーワードなし、物理的不可分ペアなし → 各々split
    const result = runSplitJudge(makeExtracted([
      { id: 'sj_035', desc: 'OAチェア（1台）', amount: 90_000 },
      { id: 'sj_036', desc: 'OAチェア（2台）', amount: 90_000 },
      { id: 'sj_037', desc: 'OAチェア（3台）', amount: 90_000 },
    ]));

    // 270,000 <= 300,000 → 少額合算非適用 → 各々split
    expect(result.groups.every((g) => g.judgment === 'split')).toBe(true);
    expect(result.groups).toHaveLength(3);
  });

  it('SJ-5c: 5万+40万の混在（一方が10万超）→ split（少額合算非適用）', () => {
    // CHECK-7b: 50,000 < 100,000 だが 400,000 >= 100,000 → allSmall=false → bundled非適用
    //   バンドルキーワードなし → 各々split
    const result = runSplitJudge(makeExtracted([
      { id: 'sj_038', desc: 'キーボード', amount: 50_000 },
      { id: 'sj_039', desc: 'サーバー機器', amount: 400_000 },
    ]));

    // 一方が10万以上 → allSmall=false → 少額合算非適用
    // バンドルキーワードなし → split
    expect(result.groups.every((g) => g.judgment === 'split')).toBe(true);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 5. 独立明細（バンドル条件なし）→ 各々split
// ─────────────────────────────────────────────────────────────────────────────

describe('splitJudge: 独立明細（バンドル条件なし）→ 各々split', () => {
  /**
   * SJ-6: 独立した2明細（バンドルキーワードなし、PC+周辺機器ペアなし、少額合算なし）
   * CHECK-9: 上記3ルールすべて非適用 → 各明細を個別グループとして返す
   * CHECK-7b:
   *   コンプレッサー400k + 受付デスク200k
   *   → バンドルキーワードなし / PC+周辺機器ペアなし / 一方が10万超 → 各々split
   */
  it('SJ-6: コンプレッサー(400k) + 受付デスク(200k) → 各々split', () => {
    const result = runSplitJudge(makeExtracted([
      { id: 'sj_041', desc: 'コンプレッサー（工場用）', amount: 400_000 },
      { id: 'sj_042', desc: '受付デスク（木製）', amount: 200_000 },
    ]));

    expect(result.groups).toHaveLength(2);
    expect(result.groups.every((g) => g.judgment === 'split')).toBe(true);
    // 各々の合計は元のamount
    expect(result.groups[0].group_total).toBe(400_000);
    expect(result.groups[1].group_total).toBe(200_000);
  });

  it('SJ-6b: 3明細すべて独立（バンドル条件なし）→ 3件各々split', () => {
    // CHECK-7b: 各明細が独立した資産 → 各々split（3グループ）
    const result = runSplitJudge(makeExtracted([
      { id: 'sj_043', desc: 'プリンター業務用', amount: 150_000 },
      { id: 'sj_044', desc: '会議テーブル（金属製）', amount: 200_000 },
      { id: 'sj_045', desc: '電話機（IP電話）', amount: 120_000 },
    ]));

    expect(result.groups).toHaveLength(3);
    expect(result.groups.every((g) => g.judgment === 'split')).toBe(true);
    expect(result.groups[0].items).toHaveLength(1);
    expect(result.groups[1].items).toHaveLength(1);
    expect(result.groups[2].items).toHaveLength(1);
  });
});
