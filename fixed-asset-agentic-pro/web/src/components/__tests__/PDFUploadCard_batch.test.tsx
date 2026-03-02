/**
 * PDFUploadCard — F-11バッチCSVエクスポートテスト (cmd_150k_sub3)
 *
 * CHECK-9根拠:
 * - ボタン表示条件: 処理完了かつ2件以上の場合のみ表示
 * - CSVデータ内容: ファイル名・品目名・金額・判定の4列
 * - v1/v2両レスポンス形式をカバー
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { PDFUploadCard, generateBatchCsv } from '../PDFUploadCard';
import type { FileProcessResult } from '../PDFUploadCard';
import type { ClassifyResponse } from '@/types/classify';
import type { ClassifyPDFV2Response } from '@/types/classify_pdf_v2';
import { classifyFromPDF } from '@/lib/api';

// ─── モック設定 ────────────────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  classifyFromPDF: vi.fn(),
}));

vi.mock('@/lib/classify_pdf_v2', () => ({
  classifyFromPDFv2: vi.fn(),
  getUseMultiAgent: vi.fn(() => false), // v1モード
}));

// ─── テスト用モックデータ ──────────────────────────────────────────────

const mockV1Result: ClassifyResponse = {
  decision: 'CAPITAL_LIKE',
  reasons: ['テスト根拠'],
  evidence: [],
  questions: [],
  metadata: {},
  is_valid_document: true,
  confidence: 0.9,
  trace: [],
  missing_fields: [],
  why_missing_matters: [],
  citations: [],
  line_items: [
    { description: 'サーバー機器', amount: 500000, classification: 'CAPITAL_LIKE' },
    { description: 'ソフトウェアライセンス', amount: 150000, classification: 'EXPENSE_LIKE' },
  ],
  disclaimer: '',
};

const mockV1ResultExpense: ClassifyResponse = {
  ...mockV1Result,
  decision: 'EXPENSE_LIKE',
  line_items: [
    { description: '消耗品費', amount: 30000, classification: 'EXPENSE_LIKE' },
  ],
};

const mockV2Result: ClassifyPDFV2Response = {
  request_id: 'req-001',
  status: 'success',
  extracted: {
    items: [
      { line_item_id: 'li-1', description: 'PCモニター', amount: 80000 },
    ],
  },
  line_results: [
    {
      line_item_id: 'li-1',
      verdict: 'CAPITAL_LIKE',
      confidence: 0.88,
      account_category: '器具備品',
      useful_life: 5,
      tax_verdict: 'CAPITAL_LIKE',
      tax_rationale: 'テスト',
      tax_account: null,
      practice_verdict: 'CAPITAL_LIKE',
      practice_rationale: 'テスト',
      practice_account: null,
      similar_cases: [],
    },
  ],
  summary: { capital_total: 80000, expense_total: 0, guidance_total: 0, by_account: [] },
  audit_trail_id: null,
  elapsed_ms: 100,
};

// ─── generateBatchCsv ユニットテスト ──────────────────────────────────

describe('generateBatchCsv — CSV内容テスト', () => {
  it('v1レスポンス: ヘッダー4列が正しく出力される', () => {
    const fileResults: FileProcessResult[] = [
      { file: new File([''], 'invoice.pdf'), status: 'done', result: mockV1Result },
    ];
    const csv = generateBatchCsv(fileResults);
    const [header] = csv.split('\n');
    expect(header).toBe('"ファイル名","品目名","金額","判定"');
  });

  it('v1レスポンス: ファイル名・品目名・金額・判定が正しく含まれる', () => {
    const fileResults: FileProcessResult[] = [
      { file: new File([''], 'invoice.pdf'), status: 'done', result: mockV1Result },
    ];
    const csv = generateBatchCsv(fileResults);
    expect(csv).toContain('"invoice.pdf"');
    expect(csv).toContain('"サーバー機器"');
    expect(csv).toContain('"500000"');
    expect(csv).toContain('"固定資産"');
    expect(csv).toContain('"ソフトウェアライセンス"');
    expect(csv).toContain('"費用"');
  });

  it('v1レスポンス: 複数ファイルが1つのCSVに結合される', () => {
    const fileResults: FileProcessResult[] = [
      { file: new File([''], 'file1.pdf'), status: 'done', result: mockV1Result },
      { file: new File([''], 'file2.pdf'), status: 'done', result: mockV1ResultExpense },
    ];
    const csv = generateBatchCsv(fileResults);
    expect(csv).toContain('"file1.pdf"');
    expect(csv).toContain('"file2.pdf"');
    expect(csv).toContain('"サーバー機器"');
    expect(csv).toContain('"消耗品費"');
    // ヘッダーは1行のみ
    const lines = csv.split('\n');
    const headerCount = lines.filter(l => l.startsWith('"ファイル名"')).length;
    expect(headerCount).toBe(1);
  });

  it('v2レスポンス: extracted.itemsとline_resultsを結合して出力', () => {
    const fileResults: FileProcessResult[] = [
      { file: new File([''], 'v2test.pdf'), status: 'done', result: mockV2Result },
    ];
    const csv = generateBatchCsv(fileResults);
    expect(csv).toContain('"v2test.pdf"');
    expect(csv).toContain('"PCモニター"');
    expect(csv).toContain('"80000"');
    expect(csv).toContain('"固定資産"');
  });

  it('doneでないファイルはCSVに含まれない', () => {
    const fileResults: FileProcessResult[] = [
      { file: new File([''], 'done.pdf'), status: 'done', result: mockV1ResultExpense },
      { file: new File([''], 'error.pdf'), status: 'error', error: '失敗' },
      { file: new File([''], 'pending.pdf'), status: 'pending' },
    ];
    const csv = generateBatchCsv(fileResults);
    expect(csv).toContain('"done.pdf"');
    expect(csv).not.toContain('"error.pdf"');
    expect(csv).not.toContain('"pending.pdf"');
  });

  it('処理済みファイルが0件のとき空文字を返す', () => {
    const csv = generateBatchCsv([]);
    expect(csv).toBe('');
  });

  it('v1でline_itemsが空の場合はPDF判定結果行を出力', () => {
    const emptyLineItems: ClassifyResponse = {
      ...mockV1Result,
      decision: 'GUIDANCE',
      line_items: [],
    };
    const fileResults: FileProcessResult[] = [
      { file: new File([''], 'empty.pdf'), status: 'done', result: emptyLineItems },
    ];
    const csv = generateBatchCsv(fileResults);
    expect(csv).toContain('"PDF判定結果"');
    expect(csv).toContain('"要確認"');
  });

  it('ファイル名にダブルクォートが含まれる場合にエスケープされる', () => {
    const fileResults: FileProcessResult[] = [
      { file: new File([''], 'test"file.pdf'), status: 'done', result: mockV1ResultExpense },
    ];
    const csv = generateBatchCsv(fileResults);
    // " → "" でエスケープ
    expect(csv).toContain('test""file.pdf');
  });
});

// ─── PDFUploadCard — ボタン表示条件テスト ─────────────────────────────

describe('PDFUploadCard — 全件CSVエクスポートボタン表示条件', () => {
  const mockClassifyFromPDF = classifyFromPDF as ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
    mockClassifyFromPDF.mockResolvedValue(mockV1Result);
  });

  it('初期状態では全件CSVエクスポートボタンが表示されない', () => {
    render(<PDFUploadCard onResult={vi.fn()} />);
    expect(screen.queryByTestId('btn-batch-csv-export')).not.toBeInTheDocument();
  });

  it('ファイルを選択しただけではボタンが表示されない（未処理）', () => {
    render(<PDFUploadCard onResult={vi.fn()} />);
    const input = screen.getByTestId('file-input');
    fireEvent.change(input, {
      target: {
        files: [
          new File(['pdf'], 'file1.pdf', { type: 'application/pdf' }),
          new File(['pdf'], 'file2.pdf', { type: 'application/pdf' }),
        ],
      },
    });
    expect(screen.queryByTestId('btn-batch-csv-export')).not.toBeInTheDocument();
  });

  it('2件以上の処理が完了したらボタンが表示される', async () => {
    render(<PDFUploadCard onResult={vi.fn()} />);
    const input = screen.getByTestId('file-input');
    fireEvent.change(input, {
      target: {
        files: [
          new File(['pdf'], 'a.pdf', { type: 'application/pdf' }),
          new File(['pdf'], 'b.pdf', { type: 'application/pdf' }),
        ],
      },
    });
    const submitBtn = screen.getByRole('button', { name: /2件を判定する/ });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByTestId('btn-batch-csv-export')).toBeInTheDocument();
    });
    expect(screen.getByText(/全件CSVエクスポート（2件）/)).toBeInTheDocument();
  });

  it('1件のみ処理完了の場合はボタンが表示されない', async () => {
    render(<PDFUploadCard onResult={vi.fn()} />);
    const input = screen.getByTestId('file-input');
    fireEvent.change(input, {
      target: {
        files: [new File(['pdf'], 'single.pdf', { type: 'application/pdf' })],
      },
    });
    const submitBtn = screen.getByRole('button', { name: /1件を判定する/ });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText('✅ 1件の判定が完了しました')).toBeInTheDocument();
    });
    expect(screen.queryByTestId('btn-batch-csv-export')).not.toBeInTheDocument();
  });
});

// ─── PDFUploadCard — 並列化バッチ処理テスト (F-11 PARALLEL_BATCH_SIZE=3) ──
// CHECK-9根拠: Promise.allSettled MDN仕様 — 全件 settled を待つ。一部 rejected でも他は継続。
// PARALLEL_BATCH_SIZE=3: バックエンド負荷とUXのバランスから選定。

describe('PDFUploadCard — 並列バッチ処理 (PARALLEL_BATCH_SIZE=3)', () => {
  const mockClassifyFromPDF = classifyFromPDF as ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('3件投入 → classify が3回呼ばれ全件 done になる', async () => {
    // CHECK-9: 3件全て成功 → doneCount=3, totalFiles=3 → 完了メッセージ表示
    mockClassifyFromPDF.mockResolvedValue(mockV1Result);
    render(<PDFUploadCard onResult={vi.fn()} />);
    const input = screen.getByTestId('file-input');
    fireEvent.change(input, {
      target: {
        files: [
          new File(['pdf'], 'a.pdf', { type: 'application/pdf' }),
          new File(['pdf'], 'b.pdf', { type: 'application/pdf' }),
          new File(['pdf'], 'c.pdf', { type: 'application/pdf' }),
        ],
      },
    });
    const submitBtn = screen.getByRole('button', { name: /3件を判定する/ });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText('✅ 3件の判定が完了しました')).toBeInTheDocument();
    });
    // 全3件が処理されたことを確認（並列・逐次問わず全件呼ばれること）
    expect(mockClassifyFromPDF).toHaveBeenCalledTimes(3);
    // 全件CSVエクスポートボタンも表示される
    expect(screen.getByTestId('btn-batch-csv-export')).toBeInTheDocument();
  });

  it('1件失敗 → 他2件は継続処理される（Promise.allSettled の性質）', async () => {
    // CHECK-9: allSettled は一部 rejected でも残り fulfilled を返す
    mockClassifyFromPDF
      .mockResolvedValueOnce(mockV1Result)           // file 1: 成功
      .mockRejectedValueOnce(new Error('API error')) // file 2: 失敗
      .mockResolvedValueOnce(mockV1ResultExpense);   // file 3: 成功
    render(<PDFUploadCard onResult={vi.fn()} />);
    const input = screen.getByTestId('file-input');
    fireEvent.change(input, {
      target: {
        files: [
          new File(['pdf'], 'ok1.pdf', { type: 'application/pdf' }),
          new File(['pdf'], 'fail.pdf', { type: 'application/pdf' }),
          new File(['pdf'], 'ok2.pdf', { type: 'application/pdf' }),
        ],
      },
    });
    const submitBtn = screen.getByRole('button', { name: /3件を判定する/ });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      // エラーバッジが1件表示される（失敗したファイルのみ）
      expect(screen.getAllByText('エラー')).toHaveLength(1);
    });
    // 全3件が呼ばれた（失敗しても他は継続 = allSettled の動作確認）
    expect(mockClassifyFromPDF).toHaveBeenCalledTimes(3);
    // doneCount(2) !== totalFiles(3) → 完了メッセージは出ない
    expect(screen.queryByText(/✅ 3件の判定が完了しました/)).not.toBeInTheDocument();
  });

  it('4件投入 → classify が4回呼ばれ全件 done になる（3+1の2バッチ想定）', async () => {
    // CHECK-9: PARALLEL_BATCH_SIZE=3 の場合、4件は 3+1 の2バッチで処理される
    mockClassifyFromPDF.mockResolvedValue(mockV1Result);
    render(<PDFUploadCard onResult={vi.fn()} />);
    const input = screen.getByTestId('file-input');
    fireEvent.change(input, {
      target: {
        files: [
          new File(['pdf'], 'a.pdf', { type: 'application/pdf' }),
          new File(['pdf'], 'b.pdf', { type: 'application/pdf' }),
          new File(['pdf'], 'c.pdf', { type: 'application/pdf' }),
          new File(['pdf'], 'd.pdf', { type: 'application/pdf' }),
        ],
      },
    });
    const submitBtn = screen.getByRole('button', { name: /4件を判定する/ });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText('✅ 4件の判定が完了しました')).toBeInTheDocument();
    });
    // 4件全てが処理された
    expect(mockClassifyFromPDF).toHaveBeenCalledTimes(4);
  });
});
