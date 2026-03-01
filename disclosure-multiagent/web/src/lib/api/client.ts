import type { CompanyInfo, EdinetDocument, PipelineStatus } from '@/types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json();
}

// ── EDINET / Company Search ──────────────────────────────

export async function searchCompany(params: {
  sec_code?: string;
  edinet_code?: string;
  name?: string;
}): Promise<{ results: CompanyInfo[]; total: number }> {
  const qs = new URLSearchParams();
  if (params.sec_code) qs.set('sec_code', params.sec_code);
  if (params.edinet_code) qs.set('edinet_code', params.edinet_code);
  if (params.name) qs.set('name', params.name);
  return fetchJson(`/api/edinet/search?${qs}`);
}

export async function getEdinetDocuments(
  date: string,
  docType = '120'
): Promise<{ documents: EdinetDocument[]; total: number }> {
  return fetchJson(`/api/edinet/documents?date=${date}&doc_type=${docType}`);
}

// ── Analysis ─────────────────────────────────────────────

export async function startAnalysis(params: {
  edinet_code?: string;
  sec_code?: string;
  company_name?: string;
  fiscal_year?: number;
  fiscal_month_end?: number;
  level?: string;
  pdf_doc_id?: string;
  use_mock?: boolean;
}): Promise<{ task_id: string; status: string; message: string }> {
  return fetchJson('/api/analyze', {
    method: 'POST',
    body: JSON.stringify({
      edinet_code: params.edinet_code,
      sec_code: params.sec_code,
      company_name: params.company_name || '',
      fiscal_year: params.fiscal_year || 2025,
      fiscal_month_end: params.fiscal_month_end || 3,
      level: params.level || '竹',
      pdf_doc_id: params.pdf_doc_id,
      use_mock: params.use_mock ?? true,
    }),
  });
}

export async function getTaskStatus(taskId: string): Promise<PipelineStatus> {
  return fetchJson(`/api/status/${taskId}`);
}

// ── SSE Stream ───────────────────────────────────────────

export function streamTaskStatus(
  taskId: string,
  onUpdate: (status: PipelineStatus) => void,
  onComplete: (status: PipelineStatus) => void,
  onError?: (error: Error) => void
): () => void {
  const eventSource = new EventSource(`${API_BASE}/api/status/${taskId}/stream`);

  eventSource.addEventListener('status', (event) => {
    try {
      const data = JSON.parse(event.data) as PipelineStatus;
      onUpdate(data);
    } catch (e) {
      onError?.(e as Error);
    }
  });

  eventSource.addEventListener('complete', (event) => {
    try {
      const data = JSON.parse(event.data) as PipelineStatus;
      onComplete(data);
    } catch (e) {
      onError?.(e as Error);
    }
    eventSource.close();
  });

  eventSource.onerror = () => {
    onError?.(new Error('SSE connection error'));
    eventSource.close();
  };

  return () => eventSource.close();
}
