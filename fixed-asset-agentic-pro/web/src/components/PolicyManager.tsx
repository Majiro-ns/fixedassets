'use client';

/**
 * PolicyManager: クライアント別ポリシー管理 UI
 * 根拠: cmd_170k_sub2 Phase 3 クライアント別ポリシー管理（F-10）
 *
 * 機能:
 *   - ポリシー一覧表示（DataTable）
 *   - 作成フォーム（インラインフォーム）
 *   - 編集フォーム（行インライン編集）
 *   - 削除（確認なしで即削除）
 *   - API: GET/POST /api/v2/policies, GET/PUT/DELETE /api/v2/policies/[id]
 */

import { useState, useEffect, useCallback } from 'react';
import { Building2, Plus, Pencil, Trash2, Check, X, RefreshCw, AlertTriangle, Loader2 } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import type { Policy, CreatePolicyInput, UpdatePolicyInput } from '@/types/policy';

// ─── API クライアント関数 ───────────────────────────────────────────────────

async function fetchPolicies(): Promise<Policy[]> {
  const res = await fetch('/api/v2/policies');
  if (!res.ok) throw new Error(`一覧取得失敗: ${res.status}`);
  const data = (await res.json()) as { policies: Policy[] };
  return data.policies;
}

async function createPolicy(input: CreatePolicyInput): Promise<Policy> {
  const res = await fetch('/api/v2/policies', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    const err = (await res.json()) as { error?: string };
    throw new Error(err.error ?? `作成失敗: ${res.status}`);
  }
  return res.json() as Promise<Policy>;
}

async function updatePolicy(id: number, input: UpdatePolicyInput): Promise<Policy> {
  const res = await fetch(`/api/v2/policies/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    const err = (await res.json()) as { error?: string };
    throw new Error(err.error ?? `更新失敗: ${res.status}`);
  }
  return res.json() as Promise<Policy>;
}

async function deletePolicy(id: number): Promise<void> {
  const res = await fetch(`/api/v2/policies/${id}`, { method: 'DELETE' });
  if (!res.ok) {
    const err = (await res.json()) as { error?: string };
    throw new Error(err.error ?? `削除失敗: ${res.status}`);
  }
}

// ─── 作成フォームの初期値 ──────────────────────────────────────────────────

const EMPTY_CREATE: CreatePolicyInput = {
  client_name: '',
  threshold_amount: 200_000,
  keywords: [],
  rules: {},
};

// ─── PolicyManager コンポーネント ─────────────────────────────────────────

export function PolicyManager() {
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 作成フォーム
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [createDraft, setCreateDraft] = useState<CreatePolicyInput>(EMPTY_CREATE);
  const [createKeywordsStr, setCreateKeywordsStr] = useState('');
  const [isCreating, setIsCreating] = useState(false);

  // 編集フォーム（行インライン）
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<UpdatePolicyInput>({});
  const [editKeywordsStr, setEditKeywordsStr] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  // ─── ポリシー一覧取得 ─────────────────────────────────────────────────

  const loadPolicies = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const list = await fetchPolicies();
      setPolicies(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'ポリシーの取得に失敗しました');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPolicies();
  }, [loadPolicies]);

  // ─── 作成 ─────────────────────────────────────────────────────────────

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!createDraft.client_name.trim()) return;
    setIsCreating(true);
    setError(null);
    try {
      const keywords = createKeywordsStr
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      await createPolicy({ ...createDraft, client_name: createDraft.client_name.trim(), keywords });
      setCreateDraft(EMPTY_CREATE);
      setCreateKeywordsStr('');
      setShowCreateForm(false);
      await loadPolicies();
    } catch (e) {
      setError(e instanceof Error ? e.message : '作成に失敗しました');
    } finally {
      setIsCreating(false);
    }
  };

  // ─── 編集開始 ─────────────────────────────────────────────────────────

  const startEdit = (policy: Policy) => {
    setEditingId(policy.id);
    setEditDraft({
      client_name: policy.client_name,
      threshold_amount: policy.threshold_amount,
      keywords: policy.keywords,
      rules: policy.rules,
    });
    setEditKeywordsStr(policy.keywords.join(', '));
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditDraft({});
    setEditKeywordsStr('');
  };

  // ─── 編集保存 ─────────────────────────────────────────────────────────

  const handleSave = async (id: number) => {
    if (!editDraft.client_name?.trim()) return;
    setIsSaving(true);
    setError(null);
    try {
      const keywords = editKeywordsStr
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      await updatePolicy(id, { ...editDraft, keywords });
      cancelEdit();
      await loadPolicies();
    } catch (e) {
      setError(e instanceof Error ? e.message : '更新に失敗しました');
    } finally {
      setIsSaving(false);
    }
  };

  // ─── 削除 ─────────────────────────────────────────────────────────────

  const handleDelete = async (id: number) => {
    setError(null);
    try {
      await deletePolicy(id);
      if (editingId === id) cancelEdit();
      await loadPolicies();
    } catch (e) {
      setError(e instanceof Error ? e.message : '削除に失敗しました');
    }
  };

  // ─── レンダリング ──────────────────────────────────────────────────────

  return (
    <Card data-testid="policy-manager">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Building2 className="size-5 text-indigo-600" />
              クライアント別ポリシー管理
            </CardTitle>
            <CardDescription>
              クライアントごとの固定資産判定閾値・キーワードを管理します（F-10）
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={loadPolicies}
              disabled={isLoading}
              title="更新"
              className="h-8 w-8 p-0"
            >
              {isLoading ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => setShowCreateForm((v) => !v)}
              disabled={editingId !== null}
              className="h-8 gap-1 text-xs"
              data-testid="add-policy-button"
            >
              <Plus className="size-3.5" />
              新規追加
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">

        {/* エラー表示 */}
        {error && (
          <Alert variant="destructive">
            <AlertTriangle className="size-4" />
            <AlertTitle>エラー</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {/* ─── 作成フォーム ───────────────────────────────────────── */}
        {showCreateForm && (
          <form
            onSubmit={handleCreate}
            className="border rounded-lg p-4 space-y-3 bg-muted/30"
            data-testid="create-policy-form"
          >
            <p className="text-sm font-medium">新規ポリシー追加</p>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="create-client-name" className="text-xs">
                  クライアント名 <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="create-client-name"
                  value={createDraft.client_name}
                  onChange={(e) => setCreateDraft({ ...createDraft, client_name: e.target.value })}
                  placeholder="例: A社"
                  className="h-8 text-xs"
                  required
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="create-threshold" className="text-xs">
                  固定資産閾値（円）
                </Label>
                <Input
                  id="create-threshold"
                  type="number"
                  value={createDraft.threshold_amount ?? 200_000}
                  onChange={(e) =>
                    setCreateDraft({ ...createDraft, threshold_amount: Number(e.target.value) })
                  }
                  min={0}
                  className="h-8 text-xs"
                />
              </div>
            </div>
            <div className="space-y-1">
              <Label htmlFor="create-keywords" className="text-xs">
                カスタムキーワード（カンマ区切り）
              </Label>
              <Input
                id="create-keywords"
                value={createKeywordsStr}
                onChange={(e) => setCreateKeywordsStr(e.target.value)}
                placeholder="例: 修繕, メンテナンス, 定期点検"
                className="h-8 text-xs"
              />
            </div>
            <div className="flex gap-2 justify-end">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setShowCreateForm(false);
                  setCreateDraft(EMPTY_CREATE);
                  setCreateKeywordsStr('');
                }}
                className="h-7 text-xs"
              >
                キャンセル
              </Button>
              <Button
                type="submit"
                size="sm"
                disabled={isCreating || !createDraft.client_name.trim()}
                className="h-7 text-xs"
                data-testid="create-policy-submit"
              >
                {isCreating ? <Loader2 className="size-3 animate-spin mr-1" /> : <Plus className="size-3 mr-1" />}
                追加
              </Button>
            </div>
          </form>
        )}

        {/* ─── ポリシーテーブル ────────────────────────────────────── */}
        {policies.length === 0 && !isLoading ? (
          <p className="text-center text-sm text-muted-foreground py-6">
            ポリシーが登録されていません。「新規追加」から作成してください。
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border" data-testid="policy-table">
            <table className="w-full text-xs">
              <thead className="bg-muted">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">クライアント名</th>
                  <th className="px-3 py-2 text-right font-medium w-36">固定資産閾値（円）</th>
                  <th className="px-3 py-2 text-left font-medium">キーワード</th>
                  <th className="px-3 py-2 text-left font-medium w-32">更新日時</th>
                  <th className="px-2 py-2 text-center font-medium w-20">操作</th>
                </tr>
              </thead>
              <tbody>
                {policies.map((policy) => {
                  const isEditing = editingId === policy.id;
                  return (
                    <tr key={policy.id} className="border-t">
                      {isEditing ? (
                        /* ── 編集行 ──────────────────────────────── */
                        <>
                          <td className="px-2 py-1">
                            <Input
                              value={editDraft.client_name ?? ''}
                              onChange={(e) =>
                                setEditDraft({ ...editDraft, client_name: e.target.value })
                              }
                              className="h-7 text-xs"
                              placeholder="クライアント名"
                            />
                          </td>
                          <td className="px-2 py-1">
                            <Input
                              type="number"
                              value={editDraft.threshold_amount ?? 200_000}
                              onChange={(e) =>
                                setEditDraft({
                                  ...editDraft,
                                  threshold_amount: Number(e.target.value),
                                })
                              }
                              min={0}
                              className="h-7 text-xs text-right"
                            />
                          </td>
                          <td className="px-2 py-1">
                            <Input
                              value={editKeywordsStr}
                              onChange={(e) => setEditKeywordsStr(e.target.value)}
                              className="h-7 text-xs"
                              placeholder="カンマ区切り"
                            />
                          </td>
                          <td className="px-3 py-1 text-muted-foreground" />
                          <td className="px-2 py-1">
                            <div className="flex items-center justify-center gap-1">
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                onClick={() => handleSave(policy.id)}
                                disabled={isSaving}
                                className="h-6 w-6 p-0 text-green-600 hover:text-green-700"
                                title="保存"
                              >
                                {isSaving ? (
                                  <Loader2 className="size-3 animate-spin" />
                                ) : (
                                  <Check className="size-3.5" />
                                )}
                              </Button>
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                onClick={cancelEdit}
                                className="h-6 w-6 p-0 text-muted-foreground"
                                title="キャンセル"
                              >
                                <X className="size-3.5" />
                              </Button>
                            </div>
                          </td>
                        </>
                      ) : (
                        /* ── 表示行 ──────────────────────────────── */
                        <>
                          <td className="px-3 py-2 font-medium">{policy.client_name}</td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {policy.threshold_amount.toLocaleString()}
                          </td>
                          <td className="px-3 py-2">
                            {policy.keywords.length > 0 ? (
                              <div className="flex flex-wrap gap-1">
                                {policy.keywords.slice(0, 3).map((kw, i) => (
                                  <Badge key={i} variant="secondary" className="text-xs px-1 py-0">
                                    {kw}
                                  </Badge>
                                ))}
                                {policy.keywords.length > 3 && (
                                  <span className="text-muted-foreground text-xs">
                                    +{policy.keywords.length - 3}
                                  </span>
                                )}
                              </div>
                            ) : (
                              <span className="text-muted-foreground">—</span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-muted-foreground">
                            {policy.updated_at.slice(0, 10)}
                          </td>
                          <td className="px-2 py-2">
                            <div className="flex items-center justify-center gap-1">
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                onClick={() => startEdit(policy)}
                                disabled={editingId !== null}
                                className="h-6 w-6 p-0 text-muted-foreground hover:text-foreground"
                                title="編集"
                              >
                                <Pencil className="size-3.5" />
                              </Button>
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                onClick={() => handleDelete(policy.id)}
                                disabled={editingId !== null}
                                className="h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
                                title="削除"
                              >
                                <Trash2 className="size-3.5" />
                              </Button>
                            </div>
                          </td>
                        </>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* 件数表示 */}
        {policies.length > 0 && (
          <p className="text-xs text-muted-foreground text-right">{policies.length} 件登録済み</p>
        )}
      </CardContent>
    </Card>
  );
}
