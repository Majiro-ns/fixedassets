import { NextRequest, NextResponse } from 'next/server';
import type { ClassifyResponse } from '@/types/classify';
import type { TrainingRecord } from '@/types/training_data';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

// ─── Few-shot プロンプト構築 ───────────────────────────────────────────────
/**
 * 教師データから Few-shot 例のプロンプト文字列を生成する。
 * examples が 0 件の場合は空文字列を返す（デフォルト動作へフォールバック）。
 */
function buildFewShotSection(examples: TrainingRecord[]): string {
  if (examples.length === 0) return '';

  const lines = examples.slice(0, 10).map((ex) => {
    const labelEn =
      ex.label === '固定資産' ? 'CAPITAL_LIKE' :
      ex.label === '費用'     ? 'EXPENSE_LIKE' : 'GUIDANCE';
    const notesStr = ex.notes ? ` / 備考: ${ex.notes}` : '';
    return `- 品目: ${ex.item} / ¥${ex.amount.toLocaleString()} → ${labelEn}（${ex.label}）${notesStr}`;
  });

  return [
    `【教師データ（Few-shot ${examples.length}件）】`,
    ...lines,
  ].join('\n');
}

// ─── POST ────────────────────────────────────────────────────────────────────
export async function POST(req: NextRequest): Promise<NextResponse> {
  let body: {
    opal_json: Record<string, unknown>;
    answers?: Record<string, string>;
    few_shot_examples?: TrainingRecord[];
  };

  try {
    body = (await req.json()) as typeof body;
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const { opal_json, answers, few_shot_examples = [] } = body;

  // Few-shot プロンプト構築（教師データ 0 件ならスキップ）
  const fewShotPrompt = buildFewShotSection(few_shot_examples);
  if (fewShotPrompt) {
    // サーバーログに出力（動作確認用）
    console.log('[F-T03] Few-shot プロンプト生成:\n', fewShotPrompt);
  }

  // Python バックエンドへプロキシ（opal_json / answers のみ転送）
  let backendRes: Response;
  try {
    backendRes = await fetch(`${API_BASE}/classify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ opal_json, answers }),
    });
  } catch (err) {
    return NextResponse.json(
      { error: `Backend unavailable: ${String(err)}` },
      { status: 502 },
    );
  }

  if (!backendRes.ok) {
    const text = await backendRes.text();
    return NextResponse.json({ error: text }, { status: backendRes.status });
  }

  const data = (await backendRes.json()) as ClassifyResponse;

  // Few-shot プロンプトを metadata に追記（フロントエンドでの検証用）
  if (fewShotPrompt) {
    data.metadata = {
      ...data.metadata,
      few_shot_prompt: fewShotPrompt,
      few_shot_count: few_shot_examples.length,
    };
  }

  return NextResponse.json(data);
}
