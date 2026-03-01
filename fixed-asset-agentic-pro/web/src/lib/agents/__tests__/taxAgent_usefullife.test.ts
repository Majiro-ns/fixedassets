/**
 * taxAgent_usefullife.test.ts
 *
 * USEFUL_LIFE_MASTER (cmd_146k_sub3 追加14品目) のユニットテスト
 *
 * CHECK-9: テスト期待値の根拠
 *   全品目の耐用年数は「減価償却資産の耐用年数等に関する省令」別表第一に基づく。
 *   法令根拠: USEFUL_LIFE_MASTER の basis フィールドに明記。
 *   A3 (cmd_144k_sub5) の拡張提案と一致することを確認。
 *
 * CHECK-7b 手動検証 (代表4品目):
 *   ガス設備: 別表第一 建物附属設備（ガス設備）→ 15年 ✓
 *   棚(金属製): 別表第一 器具及び備品 1（主として金属製のもの）→ 15年 ✓
 *   棚（木製）: 別表第一 器具及び備品（その他のもの）→ 8年 ✓ (CR W-1対応)
 *   原付: 別表第一 車両及び運搬具（二輪自動車）125cc以下 → 3年 ✓
 */

import { describe, it, expect } from 'vitest';
import { USEFUL_LIFE_MASTER } from '../taxAgent';

// ─── USEFUL_LIFE_MASTER 存在確認 ────────────────────────────────────────

describe('USEFUL_LIFE_MASTER: 基本構造', () => {
  it('エクスポートされている', () => {
    expect(USEFUL_LIFE_MASTER).toBeDefined();
    expect(typeof USEFUL_LIFE_MASTER).toBe('object');
  });

  it('16品目が含まれている', () => {
    expect(Object.keys(USEFUL_LIFE_MASTER)).toHaveLength(16);
  });
});

// ─── 建物附属設備（新規4品目）────────────────────────────────────────────

describe('USEFUL_LIFE_MASTER: 建物附属設備 (4品目)', () => {
  // CHECK-9 根拠: 別表第一 建物附属設備（ガス設備）
  it('ガス設備: 15年 / 建物附属設備', () => {
    const entry = USEFUL_LIFE_MASTER['ガス設備'];
    expect(entry).toBeDefined();
    expect(entry.years).toBe(15);
    expect(entry.category).toBe('建物附属設備');
    expect(entry.basis).toContain('ガス設備');
  });

  // CHECK-9 根拠: 別表第一 建物附属設備（消火設備）
  it('スプリンクラー: 8年 / 建物附属設備 (消火設備)', () => {
    const entry = USEFUL_LIFE_MASTER['スプリンクラー'];
    expect(entry).toBeDefined();
    expect(entry.years).toBe(8);
    expect(entry.category).toBe('建物附属設備');
    expect(entry.basis).toContain('消火設備');
  });

  // CHECK-9 根拠: 別表第一 建物附属設備（冷暖房設備）
  it('空調ダクト: 13年 / 建物附属設備 (冷暖房設備)', () => {
    const entry = USEFUL_LIFE_MASTER['空調ダクト'];
    expect(entry).toBeDefined();
    expect(entry.years).toBe(13);
    expect(entry.category).toBe('建物附属設備');
    expect(entry.basis).toContain('冷暖房設備');
  });

  // CHECK-9 根拠: 別表第一 建物附属設備（可動間仕切り、金属製）
  it('間仕切り: 15年 / 建物附属設備 (可動間仕切り)', () => {
    const entry = USEFUL_LIFE_MASTER['間仕切り'];
    expect(entry).toBeDefined();
    expect(entry.years).toBe(15);
    expect(entry.category).toBe('建物附属設備');
    expect(entry.basis).toContain('間仕切り');
  });
});

// ─── 器具及び備品・家具棚系（4品目）────────────────────────────────────

describe('USEFUL_LIFE_MASTER: 器具及び備品 - 家具・棚系 (4品目)', () => {
  // CHECK-9 根拠: 別表第一 器具及び備品 1（主として金属製のもの）
  it('棚: 15年 / 器具及び備品 (金属製)', () => {
    const entry = USEFUL_LIFE_MASTER['棚'];
    expect(entry).toBeDefined();
    expect(entry.years).toBe(15);
    expect(entry.category).toBe('器具及び備品');
    expect(entry.note).toContain('木製棚は8年');
  });

  // CHECK-9 根拠: 別表第一 器具及び備品 1（主として金属製のもの）
  it('ロッカー: 15年 / 器具及び備品 (金属製)', () => {
    const entry = USEFUL_LIFE_MASTER['ロッカー'];
    expect(entry).toBeDefined();
    expect(entry.years).toBe(15);
    expect(entry.category).toBe('器具及び備品');
  });

  // CHECK-9 根拠: 別表第一 器具及び備品 1（主として金属製のもの）—事務机
  it('会議テーブル: 15年 / 器具及び備品 (金属製)', () => {
    const entry = USEFUL_LIFE_MASTER['会議テーブル'];
    expect(entry).toBeDefined();
    expect(entry.years).toBe(15);
    expect(entry.category).toBe('器具及び備品');
    expect(entry.note).toContain('木製は8年');
  });

  // CHECK-9 根拠: 別表第一 器具及び備品（その他のもの）— CR W-1対応 cmd_147k_sub1
  it('棚（木製）: 8年 / 器具及び備品 (その他のもの)', () => {
    const entry = USEFUL_LIFE_MASTER['棚（木製）'];
    expect(entry).toBeDefined();
    expect(entry.years).toBe(8);
    expect(entry.category).toBe('器具及び備品');
    expect(entry.note).toContain('木製棚は8年');
  });

  // CHECK-9 根拠: 別表第一 器具及び備品（その他のもの）— CR W-1対応 cmd_147k_sub1
  it('会議テーブル（木製）: 8年 / 器具及び備品 (その他のもの)', () => {
    const entry = USEFUL_LIFE_MASTER['会議テーブル（木製）'];
    expect(entry).toBeDefined();
    expect(entry.years).toBe(8);
    expect(entry.category).toBe('器具及び備品');
    expect(entry.note).toContain('木製は8年');
  });

  // CHECK-9 根拠: 材質違いでも金属製は従来通り15年を維持（回帰テスト）
  it('棚（金属製）: 15年のまま変化なし（回帰）', () => {
    const entry = USEFUL_LIFE_MASTER['棚'];
    expect(entry).toBeDefined();
    expect(entry.years).toBe(15);
    expect(entry.note).toContain('木製棚は8年');
  });

  // CHECK-9 根拠: 別表第一 器具及び備品（その他のもの）実務上8年
  it('ホワイトボード: 8年 / 器具及び備品 (その他)', () => {
    const entry = USEFUL_LIFE_MASTER['ホワイトボード'];
    expect(entry).toBeDefined();
    expect(entry.years).toBe(8);
    expect(entry.category).toBe('器具及び備品');
  });
});

// ─── 器具及び備品・電気機器系（4品目）───────────────────────────────────

describe('USEFUL_LIFE_MASTER: 器具及び備品 - 電気機器系 (4品目)', () => {
  // CHECK-9 根拠: 別表第一 器具及び備品（電気機器）
  it('テレビ: 5年 / 器具及び備品 (電気機器)', () => {
    const entry = USEFUL_LIFE_MASTER['テレビ'];
    expect(entry).toBeDefined();
    expect(entry.years).toBe(5);
    expect(entry.category).toBe('器具及び備品');
  });

  // CHECK-9 根拠: 別表第一 器具及び備品（家庭用電器）
  it('冷蔵庫: 6年 / 器具及び備品 (家庭用電器)', () => {
    const entry = USEFUL_LIFE_MASTER['冷蔵庫'];
    expect(entry).toBeDefined();
    expect(entry.years).toBe(6);
    expect(entry.category).toBe('器具及び備品');
  });

  // CHECK-9 根拠: 別表第一 器具及び備品（自動販売機）
  it('自動販売機: 5年 / 器具及び備品 (自動販売機)', () => {
    const entry = USEFUL_LIFE_MASTER['自動販売機'];
    expect(entry).toBeDefined();
    expect(entry.years).toBe(5);
    expect(entry.category).toBe('器具及び備品');
    expect(entry.basis).toContain('自動販売機');
  });

  // CHECK-9 根拠: 別表第一 器具及び備品（電気機器類）実務3〜5年
  it('電動台車: 4年 / 器具及び備品 (電気機器類)', () => {
    const entry = USEFUL_LIFE_MASTER['電動台車'];
    expect(entry).toBeDefined();
    expect(entry.years).toBe(4);
    expect(entry.category).toBe('器具及び備品');
  });
});

// ─── 器具及び備品・その他（1品目）──────────────────────────────────────

describe('USEFUL_LIFE_MASTER: 器具及び備品 - その他 (1品目)', () => {
  // CHECK-9 根拠: 別表第一 器具及び備品（その他のもの）
  it('カーテン: 3年 / 器具及び備品 (その他)', () => {
    const entry = USEFUL_LIFE_MASTER['カーテン'];
    expect(entry).toBeDefined();
    expect(entry.years).toBe(3);
    expect(entry.category).toBe('器具及び備品');
  });
});

// ─── 車両運搬具（1品目）────────────────────────────────────────────────

describe('USEFUL_LIFE_MASTER: 車両運搬具 (1品目)', () => {
  // CHECK-9 根拠: 別表第一 車両及び運搬具（二輪自動車）125cc以下
  it('原付: 3年 / 車両運搬具 (二輪自動車)', () => {
    const entry = USEFUL_LIFE_MASTER['原付'];
    expect(entry).toBeDefined();
    expect(entry.years).toBe(3);
    expect(entry.category).toBe('車両運搬具');
    expect(entry.basis).toContain('二輪自動車');
  });
});

// ─── データ整合性テスト ──────────────────────────────────────────────────

describe('USEFUL_LIFE_MASTER: データ整合性', () => {
  it('全エントリに years, category, basis が存在する', () => {
    for (const [keyword, entry] of Object.entries(USEFUL_LIFE_MASTER)) {
      expect(entry.years, `${keyword}.years`).toBeTypeOf('number');
      expect(entry.years, `${keyword}.years > 0`).toBeGreaterThan(0);
      expect(entry.category, `${keyword}.category`).toBeTypeOf('string');
      expect(entry.category, `${keyword}.category not empty`).not.toBe('');
      expect(entry.basis, `${keyword}.basis`).toBeTypeOf('string');
      expect(entry.basis, `${keyword}.basis not empty`).not.toBe('');
    }
  });

  it('カテゴリは有効な勘定科目のみ', () => {
    const validCategories = new Set(['建物附属設備', '器具及び備品', '車両運搬具', '機械装置', '建物', '無形固定資産']);
    for (const [keyword, entry] of Object.entries(USEFUL_LIFE_MASTER)) {
      expect(validCategories.has(entry.category), `${keyword}.category: ${entry.category}`).toBe(true);
    }
  });
});
