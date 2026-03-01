import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { PDFUploadCard } from '../PDFUploadCard';

// classifyFromPDF をモック
vi.mock('@/lib/api', () => ({
  classifyFromPDF: vi.fn(),
}));

describe('PDFUploadCard', () => {
  const noop = vi.fn();

  it('renders the upload zone and title', () => {
    render(<PDFUploadCard onResult={noop} />);
    expect(screen.getByText('PDFをアップロードして判定')).toBeInTheDocument();
    expect(screen.getByTestId('drop-zone')).toBeInTheDocument();
  });

  it('shows "PDFがない場合は手入力モードへ" link when onManualInput is provided', () => {
    const onManualInput = vi.fn();
    render(<PDFUploadCard onResult={noop} onManualInput={onManualInput} />);
    const link = screen.getByText('PDFがない場合は手入力モードへ');
    expect(link).toBeInTheDocument();
    fireEvent.click(link);
    expect(onManualInput).toHaveBeenCalledTimes(1);
  });

  it('does not show manual input link when onManualInput is not provided', () => {
    render(<PDFUploadCard onResult={noop} />);
    expect(screen.queryByText('PDFがない場合は手入力モードへ')).not.toBeInTheDocument();
  });

  it('accepts PDF files via file input', () => {
    render(<PDFUploadCard onResult={noop} />);
    const input = screen.getByTestId('file-input') as HTMLInputElement;
    const file = new File(['pdf content'], 'invoice.pdf', { type: 'application/pdf' });
    fireEvent.change(input, { target: { files: [file] } });
    expect(screen.getByText('invoice.pdf')).toBeInTheDocument();
  });

  it('allows removing a selected file', () => {
    render(<PDFUploadCard onResult={noop} />);
    const input = screen.getByTestId('file-input') as HTMLInputElement;
    const file = new File(['pdf'], 'test.pdf', { type: 'application/pdf' });
    fireEvent.change(input, { target: { files: [file] } });
    expect(screen.getByText('test.pdf')).toBeInTheDocument();
    const removeBtn = screen.getByLabelText('削除');
    fireEvent.click(removeBtn);
    expect(screen.queryByText('test.pdf')).not.toBeInTheDocument();
  });

  it('handles drag-over state', () => {
    render(<PDFUploadCard onResult={noop} />);
    const dropZone = screen.getByTestId('drop-zone');
    fireEvent.dragOver(dropZone, { preventDefault: vi.fn() });
    expect(screen.getByText('ここにドロップ')).toBeInTheDocument();
    fireEvent.dragLeave(dropZone);
    expect(screen.getByText('ドラッグ＆ドロップ、またはクリックして選択')).toBeInTheDocument();
  });

  it('limits file count to MAX_FILES (10)', () => {
    render(<PDFUploadCard onResult={noop} />);
    const input = screen.getByTestId('file-input') as HTMLInputElement;
    // 12ファイル追加 → 10件に切り詰め
    const files = Array.from({ length: 12 }, (_, i) =>
      new File(['pdf'], `file${i}.pdf`, { type: 'application/pdf' })
    );
    fireEvent.change(input, { target: { files } });
    expect(screen.getByText('上限(10件)に達しました')).toBeInTheDocument();
  });

  it('submit button is disabled when no files selected', () => {
    render(<PDFUploadCard onResult={noop} />);
    const btn = screen.getByRole('button', { name: /PDFを選択してください/ });
    expect(btn).toBeDisabled();
  });
});
