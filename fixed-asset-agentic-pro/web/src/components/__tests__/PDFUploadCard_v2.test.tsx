/**
 * PDFUploadCard v2 / Feature Flag テスト
 * 根拠:
 *   - Section 5.2: POST /v2/classify_pdf API 仕様
 *   - Section 12: Feature Flag USE_MULTI_AGENT
 *
 * テスト構成:
 *   Group 1: v2 APIレスポンス型定義バリデーション          → 即実行可能
 *   Group 2: convertV2ToLineItems 変換ロジック              → 即実行可能
 *   Group 3: Feature Flag切替（describe.skip）              → Phase 1-B実装後に有効化
 *   Group 4: PDFUploadCard v2統合（describe.skip）          → Phase 1-B実装後に有効化
 *
 * 注意: vi.mock は vitest にホイスティングされるため必ずトップレベルで宣言する。
 *       it()内での vi.mock 使用は禁止（ReferenceError の原因）。
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { PDFUploadCard } from '../PDFUploadCard';
import {
  convertV2ToLineItems,
  getUseMultiAgent,
} from '@/lib/classify_pdf_v2';
import type {
  ClassifyPDFV2Response,
  LineResultV2,
} from '@/types/classify_pdf_v2';

// ─── モジュールモック（トップレベルで宣言 — ホイスティング必須） ───────────
// vi.mock はファイル先頭にホイストされる。vi.fn() のみ使用可（外部変数参照禁止）

vi.mock('@/lib/api', () => ({
  classifyFromPDF: vi.fn(),
  classifyAsset: vi.fn(),
}));

vi.mock('@/lib/classify_pdf_v2', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/classify_pdf_v2')>();
  return {
    ...actual,
    classifyFromPDFv2: vi.fn(),
    getUseMultiAgent: vi.fn(() => false), // デフォルト false (Section 12)
  };
});

// ─── モック済みインポート ──────────────────────────────────────────────────
import * as apiModule from '@/lib/api';
import * as v2Module from '@/lib/classify_pdf_v2';

// ─── テストデータ（Section 5.2 準拠） ────────────────────────────────────

const mockLineResult: LineResultV2 = {
  line_item_id: 'li_001',
  verdict: 'CAPITAL_LIKE',
  confidence: 0.92,
  account_category: '器具備品',
  useful_life: 4,
  tax_verdict: 'CAPITAL',
  tax_rationale: '電子計算機 別表一 器具及び備品',
  tax_account: '器具備品',
  practice_verdict: 'CAPITAL',
  practice_rationale: '取得価額25万円以上。通常固定資産として計上。',
  practice_account: '器具備品',
  similar_cases: ['case_001', 'case_002'],
};

/** 正常レスポンス（status: success） */
const mockV2SuccessResponse: ClassifyPDFV2Response = {
  request_id: 'req_test_001',
  status: 'success',
  extracted: {
    document_date: '2026-03-01',
    vendor: 'テスト株式会社',
    items: [
      {
        line_item_id: 'li_001',
        description: 'ノートPC Dell Latitude 5540',
        amount: 250000,
        quantity: 1,
      },
    ],
  },
  line_results: [mockLineResult],
  summary: {
    capital_total: 250000,
    expense_total: 0,
    guidance_total: 0,
    by_account: [{ account_category: '器具備品', count: 1, total_amount: 250000 }],
  },
  audit_trail_id: null,
  elapsed_ms: 1234,
};

/** 抽出失敗レスポンス（status: extraction_failed） */
const mockV2ExtractionFailed: ClassifyPDFV2Response = {
  request_id: 'req_test_002',
  status: 'extraction_failed',
  extracted: null,    // Section 5.2: extraction_failed 時は null
  line_results: [],   // Section 5.2: extraction_failed 時は []
  summary: {
    capital_total: 0,
    expense_total: 0,
    guidance_total: 0,
    by_account: [],
  },
  audit_trail_id: null,
  elapsed_ms: 500,
};

/** 部分成功レスポンス（status: partial） */
const mockV2PartialResponse: ClassifyPDFV2Response = {
  ...mockV2SuccessResponse,
  request_id: 'req_test_003',
  status: 'partial',
};

/** 費用判定レスポンス（EXPENSE_LIKE） */
const mockV2ExpenseResponse: ClassifyPDFV2Response = {
  request_id: 'req_test_004',
  status: 'success',
  extracted: {
    document_date: '2026-03-01',
    vendor: 'オフィス用品店',
    items: [
      { line_item_id: 'li_002', description: 'コピー用紙 A4 500枚×10', amount: 5000, quantity: 10 },
    ],
  },
  line_results: [
    {
      line_item_id: 'li_002',
      verdict: 'EXPENSE_LIKE',
      confidence: 0.98,
      account_category: '消耗品費',
      useful_life: null,
      tax_verdict: 'EXPENSE',
      tax_rationale: '取得価額5千円 < 10万円 → 消耗品費として即時費用化（法令133条）',
      tax_account: '消耗品費',
      practice_verdict: 'EXPENSE',
      practice_rationale: '消耗品。即時費用計上。',
      practice_account: '消耗品費',
      similar_cases: [],
    },
  ],
  summary: {
    capital_total: 0,
    expense_total: 5000,
    guidance_total: 0,
    by_account: [{ account_category: '消耗品費', count: 1, total_amount: 5000 }],
  },
  audit_trail_id: 'trail_abc123',
  elapsed_ms: 980,
};

// ─────────────────────────────────────────────────────────────────────────────
// Group 1: v2 APIレスポンス型定義バリデーション（Section 5.2 準拠・即実行可能）
// ─────────────────────────────────────────────────────────────────────────────

describe('Group1: v2 APIレスポンス型定義バリデーション（Section 5.2準拠）', () => {
  it('成功レスポンスの必須フィールドが全て存在すること', () => {
    // CHECK-9: Section 5.2 レスポンス仕様の必須フィールド
    expect(mockV2SuccessResponse).toHaveProperty('request_id');
    expect(mockV2SuccessResponse).toHaveProperty('status');
    expect(mockV2SuccessResponse).toHaveProperty('extracted');
    expect(mockV2SuccessResponse).toHaveProperty('line_results');
    expect(mockV2SuccessResponse).toHaveProperty('summary');
    expect(mockV2SuccessResponse).toHaveProperty('audit_trail_id');
    expect(mockV2SuccessResponse).toHaveProperty('elapsed_ms');
  });

  it('status値は success | partial | extraction_failed のいずれかであること', () => {
    // CHECK-9: Section 5.2 status 定義（3値）
    const validStatuses: ClassifyPDFV2Response['status'][] = [
      'success', 'partial', 'extraction_failed',
    ];
    expect(validStatuses).toContain(mockV2SuccessResponse.status);
    expect(validStatuses).toContain(mockV2ExtractionFailed.status);
    expect(validStatuses).toContain(mockV2PartialResponse.status);
  });

  it('extraction_failed 時は extracted=null かつ line_results=[] であること', () => {
    // CHECK-9: Section 5.2 "extraction_failed の場合は extracted: null、line_results: []"
    expect(mockV2ExtractionFailed.extracted).toBeNull();
    expect(mockV2ExtractionFailed.line_results).toHaveLength(0);
  });

  it('line_result の verdict は CAPITAL_LIKE | EXPENSE_LIKE | GUIDANCE のいずれかであること', () => {
    // CHECK-9: Section 1.2 判定値用語対応
    const validVerdicts: LineResultV2['verdict'][] = [
      'CAPITAL_LIKE', 'EXPENSE_LIKE', 'GUIDANCE',
    ];
    for (const lr of mockV2SuccessResponse.line_results) {
      expect(validVerdicts).toContain(lr.verdict);
    }
  });

  it('confidence は 0.0 以上 1.0 以下の数値であること', () => {
    for (const lr of mockV2SuccessResponse.line_results) {
      expect(typeof lr.confidence).toBe('number');
      expect(lr.confidence).toBeGreaterThanOrEqual(0);
      expect(lr.confidence).toBeLessThanOrEqual(1);
    }
  });

  it('CAPITAL_LIKE 判定の useful_life は 1 以上の整数であること', () => {
    // CHECK-9: ゴールドデータ整合性チェックと同根拠（法令耐用年数省令別表一）
    const capitalResults = mockV2SuccessResponse.line_results.filter(
      (lr) => lr.verdict === 'CAPITAL_LIKE',
    );
    for (const lr of capitalResults) {
      if (lr.useful_life !== null) {
        expect(Number.isInteger(lr.useful_life)).toBe(true);
        expect(lr.useful_life).toBeGreaterThanOrEqual(1);
      }
    }
  });

  it('EXPENSE_LIKE 判定の useful_life は null であること', () => {
    // CHECK-9: 費用計上は耐用年数なし（即時費用化）
    const expenseResults = mockV2ExpenseResponse.line_results.filter(
      (lr) => lr.verdict === 'EXPENSE_LIKE',
    );
    for (const lr of expenseResults) {
      expect(lr.useful_life).toBeNull();
    }
  });

  it('summary の capital_total + expense_total + guidance_total が by_account 合計と一致すること', () => {
    // CHECK-7b: 手計算検証 — 250000 = 器具備品 250000
    const { capital_total, expense_total, guidance_total } = mockV2SuccessResponse.summary;
    const byAccountTotal = mockV2SuccessResponse.summary.by_account.reduce(
      (sum, a) => sum + a.total_amount, 0,
    );
    expect(byAccountTotal).toBe(capital_total + expense_total + guidance_total);
  });

  it('request_id は空でない文字列であること', () => {
    expect(typeof mockV2SuccessResponse.request_id).toBe('string');
    expect(mockV2SuccessResponse.request_id.length).toBeGreaterThan(0);
  });

  it('elapsed_ms は 0 以上の数値であること', () => {
    expect(typeof mockV2SuccessResponse.elapsed_ms).toBe('number');
    expect(mockV2SuccessResponse.elapsed_ms).toBeGreaterThanOrEqual(0);
  });

  it('audit_trail_id は string または null であること', () => {
    // Section 12: AUDIT_TRAIL_ENABLED=false の時 null
    expect(
      mockV2SuccessResponse.audit_trail_id === null ||
      typeof mockV2SuccessResponse.audit_trail_id === 'string',
    ).toBe(true);
    expect(mockV2ExpenseResponse.audit_trail_id).toBe('trail_abc123');
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Group 2: convertV2ToLineItems 変換ロジック（即実行可能）
// ─────────────────────────────────────────────────────────────────────────────

describe('Group2: convertV2ToLineItems 変換ロジック', () => {
  it('成功レスポンスから LineItemWithAction[] に変換できること', () => {
    const items = convertV2ToLineItems(mockV2SuccessResponse);
    expect(items).toHaveLength(1);
    expect(items[0].id).toBe('li_001');
    expect(items[0].description).toBe('ノートPC Dell Latitude 5540');
    expect(items[0].amount).toBe(250000);
  });

  it('verdict が正しく変換されること', () => {
    const items = convertV2ToLineItems(mockV2SuccessResponse);
    expect(items[0].verdict).toBe('CAPITAL_LIKE');
    expect(items[0].finalVerdict).toBe('CAPITAL_LIKE');
  });

  it('confidence が正しく保持されること', () => {
    const items = convertV2ToLineItems(mockV2SuccessResponse);
    expect(items[0].confidence).toBe(0.92);
  });

  it('userAction の初期値が pending であること', () => {
    // CHECK-9: Section 7.2 ボタン補正UI — 初期は未確定(pending)
    const items = convertV2ToLineItems(mockV2SuccessResponse);
    expect(items[0].userAction).toBe('pending');
  });

  it('rationale に tax_rationale が設定されること', () => {
    const items = convertV2ToLineItems(mockV2SuccessResponse);
    expect(items[0].rationale).toBe('電子計算機 別表一 器具及び備品');
  });

  it('extraction_failed の場合は空配列を返すこと', () => {
    // CHECK-9: Section 5.2 "extraction_failed → UI は手入力モードへ誘導"
    const items = convertV2ToLineItems(mockV2ExtractionFailed);
    expect(items).toHaveLength(0);
  });

  it('extracted が null の場合は空配列を返すこと', () => {
    const response: ClassifyPDFV2Response = {
      ...mockV2SuccessResponse,
      status: 'partial',
      extracted: null,
      line_results: [],
    };
    expect(convertV2ToLineItems(response)).toHaveLength(0);
  });

  it('複数の line_results を正しく変換できること', () => {
    const multiResponse: ClassifyPDFV2Response = {
      ...mockV2SuccessResponse,
      extracted: {
        items: [
          { line_item_id: 'li_001', description: 'ノートPC', amount: 250000 },
          { line_item_id: 'li_002', description: 'コピー用紙', amount: 5000 },
        ],
      },
      line_results: [
        mockLineResult,
        { ...mockLineResult, line_item_id: 'li_002', verdict: 'EXPENSE_LIKE', confidence: 0.98 },
      ],
    };
    const items = convertV2ToLineItems(multiResponse);
    expect(items).toHaveLength(2);
    expect(items[1].verdict).toBe('EXPENSE_LIKE');
  });

  it('EXPENSE_LIKE の verdict と finalVerdict が一致すること', () => {
    const items = convertV2ToLineItems(mockV2ExpenseResponse);
    expect(items[0].verdict).toBe('EXPENSE_LIKE');
    expect(items[0].finalVerdict).toBe('EXPENSE_LIKE');
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Group 3: Feature Flag 切替（Phase 1-B 実装後に有効化）
// ─────────────────────────────────────────────────────────────────────────────

describe.skip('Group3: Feature Flag 切替（Phase 1-B実装後に有効化 — Section 12準拠）', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('NEXT_PUBLIC_USE_MULTI_AGENT=true の時 getUseMultiAgent() が true を返すこと', () => {
    vi.stubEnv('NEXT_PUBLIC_USE_MULTI_AGENT', 'true');
    vi.mocked(v2Module.getUseMultiAgent).mockReturnValue(true);
    expect(v2Module.getUseMultiAgent()).toBe(true);
  });

  it('NEXT_PUBLIC_USE_MULTI_AGENT=false の時 getUseMultiAgent() が false を返すこと', () => {
    vi.stubEnv('NEXT_PUBLIC_USE_MULTI_AGENT', 'false');
    vi.mocked(v2Module.getUseMultiAgent).mockReturnValue(false);
    expect(v2Module.getUseMultiAgent()).toBe(false);
  });

  it('NEXT_PUBLIC_USE_MULTI_AGENT 未設定の時 デフォルト false を返すこと', () => {
    // CHECK-9: Section 12 "デフォルト: false（初回リリース後 true に段階切替）"
    vi.stubEnv('NEXT_PUBLIC_USE_MULTI_AGENT', '');
    vi.mocked(v2Module.getUseMultiAgent).mockReturnValue(false);
    expect(v2Module.getUseMultiAgent()).toBe(false);
  });

  it('USE_MULTI_AGENT=true → classifyFromPDFv2 が呼ばれること', async () => {
    // Phase 1-B で PDFUploadCard が Feature Flag を見て classifyFromPDFv2 を呼ぶことを検証
    vi.mocked(v2Module.getUseMultiAgent).mockReturnValue(true);
    vi.mocked(v2Module.classifyFromPDFv2).mockResolvedValue(mockV2SuccessResponse);

    const onResult = vi.fn();
    render(<PDFUploadCard onResult={onResult} />);

    const input = screen.getByTestId('file-input');
    fireEvent.change(input, {
      target: {
        files: [new File(['%PDF-1.4'], 'test.pdf', { type: 'application/pdf' })],
      },
    });

    fireEvent.click(screen.getByRole('button', { name: /判定する/ }));

    await waitFor(() => {
      expect(v2Module.classifyFromPDFv2).toHaveBeenCalledTimes(1);
    });
    // 既存 classifyFromPDF は呼ばれないこと
    expect(apiModule.classifyFromPDF).not.toHaveBeenCalled();
  });

  it('USE_MULTI_AGENT=false → 既存 classifyFromPDF が呼ばれること', async () => {
    vi.mocked(v2Module.getUseMultiAgent).mockReturnValue(false);
    vi.mocked(apiModule.classifyFromPDF).mockResolvedValue({
      decision: 'CAPITAL_LIKE',
      reasons: [],
      evidence: [],
      questions: [],
      metadata: {},
      is_valid_document: true,
      confidence: 0.9,
      trace: [],
      missing_fields: [],
      why_missing_matters: [],
      citations: [],
      line_items: [],
      disclaimer: '',
    });

    render(<PDFUploadCard onResult={vi.fn()} />);
    fireEvent.change(screen.getByTestId('file-input'), {
      target: {
        files: [new File(['%PDF-1.4'], 'test.pdf', { type: 'application/pdf' })],
      },
    });
    fireEvent.click(screen.getByRole('button', { name: /判定する/ }));

    await waitFor(() => {
      expect(apiModule.classifyFromPDF).toHaveBeenCalledTimes(1);
    });
    expect(v2Module.classifyFromPDFv2).not.toHaveBeenCalled();
  });

  it('USE_MULTI_AGENT 未設定（デフォルト）→ 既存 classifyFromPDF が呼ばれること', async () => {
    vi.mocked(v2Module.getUseMultiAgent).mockReturnValue(false);
    vi.mocked(apiModule.classifyFromPDF).mockResolvedValue({
      decision: 'EXPENSE_LIKE',
      reasons: [],
      evidence: [],
      questions: [],
      metadata: {},
      is_valid_document: true,
      confidence: 0.95,
      trace: [],
      missing_fields: [],
      why_missing_matters: [],
      citations: [],
      line_items: [],
      disclaimer: '',
    });

    render(<PDFUploadCard onResult={vi.fn()} />);
    fireEvent.change(screen.getByTestId('file-input'), {
      target: {
        files: [new File(['%PDF'], 'x.pdf', { type: 'application/pdf' })],
      },
    });
    fireEvent.click(screen.getByRole('button', { name: /判定する/ }));

    await waitFor(() => {
      expect(apiModule.classifyFromPDF).toHaveBeenCalledTimes(1);
    });
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Group 4: PDFUploadCard v2 統合（Phase 1-B 実装後に有効化）
// ─────────────────────────────────────────────────────────────────────────────

describe.skip('Group4: PDFUploadCard v2統合（Phase 1-B実装後に有効化）', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(v2Module.getUseMultiAgent).mockReturnValue(true);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('アップロード成功 → onResult が v2 レスポンスを受け取ること', async () => {
    vi.mocked(v2Module.classifyFromPDFv2).mockResolvedValue(mockV2SuccessResponse);

    const onResult = vi.fn();
    render(<PDFUploadCard onResult={onResult} />);

    fireEvent.change(screen.getByTestId('file-input'), {
      target: {
        files: [new File(['%PDF-1.4'], 'invoice.pdf', { type: 'application/pdf' })],
      },
    });
    fireEvent.click(screen.getByRole('button', { name: /判定する/ }));

    await waitFor(() => {
      expect(onResult).toHaveBeenCalledWith(
        expect.objectContaining({ request_id: 'req_test_001', status: 'success' }),
      );
    });
  });

  it('extraction_failed → extractionFailed=true となり手入力誘導Alertが表示されること', async () => {
    // Section 5.2: "extraction_failed の場合 → UI は手入力モードへ誘導"
    vi.mocked(v2Module.classifyFromPDFv2).mockResolvedValue(mockV2ExtractionFailed);

    const onManualInput = vi.fn();
    render(<PDFUploadCard onResult={vi.fn()} onManualInput={onManualInput} />);

    fireEvent.change(screen.getByTestId('file-input'), {
      target: {
        files: [new File(['%PDF'], 'bad.pdf', { type: 'application/pdf' })],
      },
    });
    fireEvent.click(screen.getByRole('button', { name: /判定する/ }));

    await waitFor(() => {
      expect(screen.getByText(/PDFの読み取りに失敗しました/)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/手入力モードへ/));
    expect(onManualInput).toHaveBeenCalledTimes(1);
  });

  it('ネットワークエラー → ファイルステータスが error になること', async () => {
    vi.mocked(v2Module.classifyFromPDFv2).mockRejectedValue(
      new Error('API v2 error 503: Service Unavailable'),
    );

    render(<PDFUploadCard onResult={vi.fn()} />);
    fireEvent.change(screen.getByTestId('file-input'), {
      target: {
        files: [new File(['%PDF'], 'net.pdf', { type: 'application/pdf' })],
      },
    });
    fireEvent.click(screen.getByRole('button', { name: /判定する/ }));

    await waitFor(() => {
      expect(screen.getByText(/エラー/)).toBeInTheDocument();
    });
  });

  it('アップロード中はローディング表示（X / N 処理中...）が出ること', async () => {
    // Section 7.1: "X / N 処理中..."
    vi.mocked(v2Module.classifyFromPDFv2).mockReturnValue(
      new Promise<ClassifyPDFV2Response>(() => {}), // resolve しない = ローディング維持
    );

    render(<PDFUploadCard onResult={vi.fn()} />);
    fireEvent.change(screen.getByTestId('file-input'), {
      target: {
        files: [new File(['%PDF'], 'slow.pdf', { type: 'application/pdf' })],
      },
    });
    fireEvent.click(screen.getByRole('button', { name: /判定する/ }));

    await waitFor(() => {
      expect(screen.getByText(/0 \/ 1 処理中/)).toBeInTheDocument();
    });
  });

  it('非PDFファイルは無視されること（PDFのみ受け付け）', () => {
    render(<PDFUploadCard onResult={vi.fn()} />);
    fireEvent.change(screen.getByTestId('file-input'), {
      target: {
        files: [new File(['hello'], 'note.txt', { type: 'text/plain' })],
      },
    });
    expect(screen.queryByText('note.txt')).not.toBeInTheDocument();
  });

  it('classifyFromPDFv2 が File を引数に呼ばれること', async () => {
    vi.mocked(v2Module.classifyFromPDFv2).mockResolvedValue(mockV2SuccessResponse);

    render(<PDFUploadCard onResult={vi.fn()} />);
    fireEvent.change(screen.getByTestId('file-input'), {
      target: {
        files: [new File(['%PDF-1.4'], 'test.pdf', { type: 'application/pdf' })],
      },
    });
    fireEvent.click(screen.getByRole('button', { name: /判定する/ }));

    await waitFor(() => {
      expect(v2Module.classifyFromPDFv2).toHaveBeenCalledWith(
        expect.any(File),
        expect.any(Object),
      );
    });
  });
});
