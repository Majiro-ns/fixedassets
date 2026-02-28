import { NextRequest, NextResponse } from 'next/server';
import type { TrainingRecord } from '@/types/training_data';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export async function POST(req: NextRequest): Promise<NextResponse> {
  let formData: FormData;
  try {
    formData = await req.formData();
  } catch {
    return NextResponse.json({ error: 'Invalid form data' }, { status: 400 });
  }

  let backendRes: Response;
  try {
    backendRes = await fetch(`${API_BASE}/import_pdf_training`, {
      method: 'POST',
      body: formData,
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

  const data = (await backendRes.json()) as { records: TrainingRecord[] };
  return NextResponse.json(data);
}
