import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { LineItemReviewCard } from '../LineItemReviewCard';
import type { LineItemWithAction } from '@/types/pdf_review';

// ─── テストデータファクトリ ────────────────────────────────────────────

function makeItem(overrides: Partial<LineItemWithAction> = {}): LineItemWithAction {
  return {
    id: 'test-id-1',
    description: 'サーバーラック',
    amount: 2000000,
    verdict: 'CAPITAL_LIKE',
    confidence: 0.95,
    userAction: 'pending',
    finalVerdict: 'CAPITAL_LIKE',
    ...overrides,
  };
}

describe('LineItemReviewCard', () => {
  // ─── 信頼度 >= 0.80 のボタン ──────────────────────────────────────

  describe('confidence >= 0.80', () => {
    it('shows [承認] [費用に変更] [保留] buttons', () => {
      const onAction = vi.fn();
      render(<LineItemReviewCard item={makeItem({ confidence: 0.95 })} onAction={onAction} />);
      expect(screen.getByTestId('btn-approve')).toBeInTheDocument();
      expect(screen.getByTestId('btn-change-expense')).toBeInTheDocument();
      expect(screen.getByTestId('btn-hold')).toBeInTheDocument();
    });

    it('calls onAction with "approved" when 承認 is clicked', () => {
      const onAction = vi.fn();
      render(<LineItemReviewCard item={makeItem({ confidence: 0.95 })} onAction={onAction} />);
      fireEvent.click(screen.getByTestId('btn-approve'));
      expect(onAction).toHaveBeenCalledWith('test-id-1', 'approved', 'CAPITAL_LIKE');
    });

    it('calls onAction with "changed_expense" / EXPENSE_LIKE when 費用に変更 is clicked', () => {
      const onAction = vi.fn();
      render(<LineItemReviewCard item={makeItem({ confidence: 0.95 })} onAction={onAction} />);
      fireEvent.click(screen.getByTestId('btn-change-expense'));
      expect(onAction).toHaveBeenCalledWith('test-id-1', 'changed_expense', 'EXPENSE_LIKE');
    });
  });

  // ─── 信頼度 0.50-0.79 のボタン ───────────────────────────────────

  describe('confidence 0.50-0.79', () => {
    it('shows [固定資産] [費用] [手入力] buttons', () => {
      const onAction = vi.fn();
      render(<LineItemReviewCard item={makeItem({ confidence: 0.65 })} onAction={onAction} />);
      expect(screen.getByTestId('btn-capital')).toBeInTheDocument();
      expect(screen.getByTestId('btn-expense')).toBeInTheDocument();
      expect(screen.getByTestId('btn-manual')).toBeInTheDocument();
    });

    it('calls onAction with "changed_capital" / CAPITAL_LIKE when 固定資産 is clicked', () => {
      const onAction = vi.fn();
      render(<LineItemReviewCard item={makeItem({ confidence: 0.65 })} onAction={onAction} />);
      fireEvent.click(screen.getByTestId('btn-capital'));
      expect(onAction).toHaveBeenCalledWith('test-id-1', 'changed_capital', 'CAPITAL_LIKE');
    });
  });

  // ─── 信頼度 < 0.50 のボタン ──────────────────────────────────────

  describe('confidence < 0.50', () => {
    it('shows [固定資産] [費用] [手入力で補正] buttons', () => {
      const onAction = vi.fn();
      render(<LineItemReviewCard item={makeItem({ confidence: 0.30 })} onAction={onAction} />);
      expect(screen.getByTestId('btn-capital')).toBeInTheDocument();
      expect(screen.getByTestId('btn-expense')).toBeInTheDocument();
      expect(screen.getByTestId('btn-manual-edit')).toBeInTheDocument();
    });

    it('calls onAction with "manual_edit" when 手入力で補正 is clicked', () => {
      const onAction = vi.fn();
      render(<LineItemReviewCard item={makeItem({ confidence: 0.30 })} onAction={onAction} />);
      fireEvent.click(screen.getByTestId('btn-manual-edit'));
      expect(onAction).toHaveBeenCalledWith('test-id-1', 'manual_edit', 'CAPITAL_LIKE');
    });
  });

  // ─── 確定済み表示 ─────────────────────────────────────────────────

  describe('confirmed item', () => {
    it('hides action buttons when confirmed', () => {
      const item = makeItem({ userAction: 'approved', confidence: 0.95 });
      render(<LineItemReviewCard item={item} onAction={vi.fn()} />);
      expect(screen.queryByTestId('action-buttons')).not.toBeInTheDocument();
    });

    it('shows "確定済み" badge when confirmed', () => {
      const item = makeItem({ userAction: 'approved', confidence: 0.95 });
      render(<LineItemReviewCard item={item} onAction={vi.fn()} />);
      expect(screen.getByText('確定済み')).toBeInTheDocument();
    });

    it('shows "✅ AI判定を承認" text when approved', () => {
      const item = makeItem({ userAction: 'approved', confidence: 0.95 });
      render(<LineItemReviewCard item={item} onAction={vi.fn()} />);
      expect(screen.getByText('✅ AI判定を承認')).toBeInTheDocument();
    });
  });

  // ─── 金額・品名表示 ───────────────────────────────────────────────

  it('displays description and formatted amount', () => {
    render(<LineItemReviewCard item={makeItem()} onAction={vi.fn()} />);
    expect(screen.getByText('サーバーラック')).toBeInTheDocument();
    expect(screen.getByText('¥2,000,000')).toBeInTheDocument();
  });

  it('shows （品名なし） when description is empty', () => {
    render(<LineItemReviewCard item={makeItem({ description: '' })} onAction={vi.fn()} />);
    expect(screen.getByText('（品名なし）')).toBeInTheDocument();
  });
});
