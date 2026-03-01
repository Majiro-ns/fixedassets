import type { ClassifyRequest, ClassifyResponse } from '@/types/classify';
import type { LeaseClassifyRequest, LeaseClassifyResponse } from '@/types/classify_lease';
import type { DepreciationRequest, DepreciationResponse } from '@/types/depreciation';
import type { TrainingRecord } from '@/types/training_data';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export async function classifyFromPDF(
  file: File,
  useGeminiVision = true,
): Promise<ClassifyResponse> {
  const formData = new FormData();
  formData.append('file', file);
  const params = new URLSearchParams({
    use_gemini_vision: useGeminiVision ? '1' : '0',
    estimate_useful_life_flag: '1',
  });
  const res = await fetch(`${API_BASE}/classify_pdf?${params}`, {
    method: 'POST',
    body: formData,
    // Content-Type は FormData 自動設定のため指定しない
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json() as Promise<ClassifyResponse>;
}

/**
 * 固定資産判定 API を呼び出す。
 * fewShotExamples が指定された場合、/api/classify (Next.js route) 経由で
 * Few-shot プロンプトを付与してから Python バックエンドへプロキシする。
 * fewShotExamples が空の場合はデフォルト動作（プロンプト追加なし）にフォールバック。
 */
export async function classifyAsset(
  req: ClassifyRequest,
  fewShotExamples: TrainingRecord[] = [],
): Promise<ClassifyResponse> {
  const opalJson = {
    description: req.description,
    amount: req.amount ?? 0,
    account: req.account ?? '',
    line_items: [
      {
        description: req.description,
        amount: req.amount ?? 0,
        account: req.account ?? '',
      },
    ],
  };

  // Few-shot examples がある場合 → Next.js route 経由（プロンプト付与）
  // ない場合 → Python バックエンド直接呼び出し（デフォルト動作）
  const endpoint =
    fewShotExamples.length > 0
      ? '/api/classify'
      : `${API_BASE}/classify`;

  const requestBody =
    fewShotExamples.length > 0
      ? { opal_json: opalJson, answers: req.answers, few_shot_examples: fewShotExamples }
      : { opal_json: opalJson, answers: req.answers };

  const res = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(requestBody),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }

  return res.json() as Promise<ClassifyResponse>;
}

export async function classifyLease(req: LeaseClassifyRequest): Promise<LeaseClassifyResponse> {
  const res = await fetch('/api/classify_lease', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json() as Promise<LeaseClassifyResponse>;
}

export async function calculateDepreciation(req: DepreciationRequest): Promise<DepreciationResponse> {
  const res = await fetch('/api/calculate_depreciation', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json() as Promise<DepreciationResponse>;
}
