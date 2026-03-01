import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { PDFReviewSection } from '../PDFReviewSection';
import type { LineItemWithAction } from '@/types/pdf_review';

// ─── テストデータ ──────────────────────────────────────────────────────

const capitalItem: LineItemWithAction = {
  id: 'item-1',
  description: 'サーバーラック',
  amount: 2000000,
  verdict: 'CAPITAL_LIKE',
  confidence: 0.95,
  userAction: 'approved',
  finalVerdict: 'CAPITAL_LIKE',
};

const expenseItem: LineItemWithAction = {
  id: 'item-2',
  description: 'エアコン修繕',
  amount: 150000,
  verdict: 'EXPENSE_LIKE',
  confidence: 0.90,
  userAction: 'approved',
  finalVerdict: 'EXPENSE_LIKE',
};

const pendingHighConf: LineItemWithAction = {
  id: 'item-3',
  description: '未確定（高信頼度）',
  amount: 500000,
  verdict: 'CAPITAL_LIKE',
  confidence: 0.85,
  userAction: 'pending',
  finalVerdict: 'CAPITAL_LIKE',
};

const pendingLowConf: LineItemWithAction = {
  id: 'item-4',
  description: '未確定（低信頼度）',
  amount: 100000,
  verdict: 'GUIDANCE',
  confidence: 0.40,
  userAction: 'pending',
  finalVerdict: 'GUIDANCE',
};

describe('PDFReviewSection', () => {
  it('renders nothing when items array is empty', () => {
    const { container } = render(
      <PDFReviewSection items={[]} onAction={vi.fn()} onApproveAll={vi.fn()} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders summary grid with capital, expense, pending counts', () => {
    const items = [capitalItem, expenseItem, pendingHighConf];
    render(<PDFReviewSection items={items} onAction={vi.fn()} onApproveAll={vi.fn()} />);
    expect(screen.getByTestId('capital-total')).toHaveTextContent('¥2,000,000');
    expect(screen.getByTestId('expense-total')).toHaveTextContent('¥150,000');
    expect(screen.getByTestId('pending-count')).toHaveTextContent('1件');
  });

  it('shows correct pending count for multiple pending items', () => {
    const items = [pendingHighConf, pendingLowConf];
    render(<PDFReviewSection items={items} onAction={vi.fn()} onApproveAll={vi.fn()} />);
    expect(screen.getByTestId('pending-count')).toHaveTextContent('2件');
  });

  it('calls onApproveAll when 全て承認 button is clicked', () => {
    const onApproveAll = vi.fn();
    render(
      <PDFReviewSection
        items={[pendingHighConf]}
        onAction={vi.fn()}
        onApproveAll={onApproveAll}
      />
    );
    const btn = screen.getByTestId('btn-approve-all');
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    expect(onApproveAll).toHaveBeenCalledTimes(1);
  });

  it('disables 全て承認 button when no high-confidence pending items', () => {
    render(
      <PDFReviewSection
        items={[pendingLowConf]}
        onAction={vi.fn()}
        onApproveAll={vi.fn()}
      />
    );
    expect(screen.getByTestId('btn-approve-all')).toBeDisabled();
  });

  it('renders CSVエクスポート button', () => {
    render(
      <PDFReviewSection
        items={[capitalItem]}
        onAction={vi.fn()}
        onApproveAll={vi.fn()}
      />
    );
    expect(screen.getByTestId('btn-csv-export')).toBeInTheDocument();
  });

  it('renders LineItemReviewCard for each item', () => {
    const items = [capitalItem, expenseItem, pendingHighConf];
    render(<PDFReviewSection items={items} onAction={vi.fn()} onApproveAll={vi.fn()} />);
    const cards = screen.getAllByTestId('line-item-review-card');
    expect(cards).toHaveLength(3);
  });

  it('capitalTotal is 0 when all items are pending', () => {
    render(
      <PDFReviewSection
        items={[pendingHighConf, pendingLowConf]}
        onAction={vi.fn()}
        onApproveAll={vi.fn()}
      />
    );
    expect(screen.getByTestId('capital-total')).toHaveTextContent('¥0');
    expect(screen.getByTestId('expense-total')).toHaveTextContent('¥0');
  });
});
