'use client';

import { useState } from 'react';
import { Pencil, Trash2, Check, X, BookOpen } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { useTrainingDataStore } from '@/store/trainingDataStore';
import type { TrainingLabel, TrainingRecord } from '@/types/training_data';

// ─── 定数 ────────────────────────────────────────────────────────────────
const VALID_LABELS: TrainingLabel[] = ['固定資産', '費用', '要確認'];
const LABEL_VARIANT: Record<TrainingLabel, 'default' | 'success' | 'warning'> = {
  固定資産: 'default',
  費用: 'success',
  要確認: 'warning',
};
const PAGE_SIZE = 20;

// ─── TrainingDataManagerCard ─────────────────────────────────────────────
/**
 * 登録済み教師データの一覧表示・個別編集・個別削除コンポーネント（F-T05）。
 * 教師データが 0 件の場合は非表示。
 */
export function TrainingDataManagerCard() {
  const { records, deleteRecord, updateRecord } = useTrainingDataStore();

  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<TrainingRecord | null>(null);
  const [page, setPage] = useState(0);

  // 教師データが未登録なら非表示
  if (records.length === 0) return null;

  const totalPages = Math.ceil(records.length / PAGE_SIZE);
  const pageRecords = records.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const startEdit = (absoluteIndex: number) => {
    setEditingIndex(absoluteIndex);
    setEditDraft({ ...records[absoluteIndex] });
  };

  const cancelEdit = () => {
    setEditingIndex(null);
    setEditDraft(null);
  };

  const saveEdit = () => {
    if (editingIndex !== null && editDraft) {
      // バリデーション（品目必須・金額正数・分類値）
      if (!editDraft.item.trim()) return;
      if (!Number.isFinite(editDraft.amount) || editDraft.amount <= 0) return;
      if (!VALID_LABELS.includes(editDraft.label)) return;
      updateRecord(editingIndex, {
        ...editDraft,
        item: editDraft.item.trim(),
        notes: editDraft.notes?.trim() || undefined,
      });
      setEditingIndex(null);
      setEditDraft(null);
    }
  };

  const handleDelete = (absoluteIndex: number) => {
    // 削除後に編集中だった場合はキャンセル
    if (editingIndex === absoluteIndex) cancelEdit();
    deleteRecord(absoluteIndex);
    // ページが空になったら前ページへ
    const newTotal = records.length - 1;
    if (page > 0 && page * PAGE_SIZE >= newTotal) {
      setPage(page - 1);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BookOpen className="size-5 text-purple-600" />
          教師データ管理
        </CardTitle>
        <CardDescription>
          登録済み {records.length} 件 — 行の編集・削除が可能です
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">

        {/* テーブル */}
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-xs">
            <thead className="bg-muted">
              <tr>
                <th className="px-2 py-2 text-left font-medium w-8">#</th>
                <th className="px-3 py-2 text-left font-medium">品目</th>
                <th className="px-3 py-2 text-right font-medium w-28">金額（円）</th>
                <th className="px-3 py-2 text-left font-medium w-24">分類</th>
                <th className="px-3 py-2 text-left font-medium">備考</th>
                <th className="px-2 py-2 text-center font-medium w-20">操作</th>
              </tr>
            </thead>
            <tbody>
              {pageRecords.map((rec, pageIdx) => {
                const absoluteIdx = page * PAGE_SIZE + pageIdx;
                const isEditing = editingIndex === absoluteIdx;

                return (
                  <tr key={absoluteIdx} className="border-t">
                    {isEditing && editDraft ? (
                      /* ── 編集行 ─────────────────────────────────── */
                      <>
                        <td className="px-2 py-1 text-muted-foreground">{absoluteIdx + 1}</td>
                        <td className="px-2 py-1">
                          <Input
                            value={editDraft.item}
                            onChange={(e) => setEditDraft({ ...editDraft, item: e.target.value })}
                            className="h-7 text-xs"
                            placeholder="品目"
                          />
                        </td>
                        <td className="px-2 py-1">
                          <Input
                            type="number"
                            value={editDraft.amount}
                            onChange={(e) =>
                              setEditDraft({ ...editDraft, amount: Number(e.target.value) })
                            }
                            className="h-7 text-xs text-right"
                            min={1}
                          />
                        </td>
                        <td className="px-2 py-1">
                          <select
                            value={editDraft.label}
                            onChange={(e) =>
                              setEditDraft({ ...editDraft, label: e.target.value as TrainingLabel })
                            }
                            className="h-7 w-full rounded-md border border-input bg-background px-2 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                          >
                            {VALID_LABELS.map((l) => (
                              <option key={l} value={l}>
                                {l}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className="px-2 py-1">
                          <Input
                            value={editDraft.notes ?? ''}
                            onChange={(e) =>
                              setEditDraft({ ...editDraft, notes: e.target.value || undefined })
                            }
                            className="h-7 text-xs"
                            placeholder="備考（任意）"
                          />
                        </td>
                        <td className="px-2 py-1">
                          <div className="flex items-center justify-center gap-1">
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              onClick={saveEdit}
                              className="h-6 w-6 p-0 text-green-600 hover:text-green-700"
                              title="保存"
                            >
                              <Check className="size-3.5" />
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
                      /* ── 表示行 ─────────────────────────────────── */
                      <>
                        <td className="px-2 py-1.5 text-muted-foreground">{absoluteIdx + 1}</td>
                        <td className="px-3 py-1.5 font-medium">{rec.item}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums">
                          {rec.amount.toLocaleString()}
                        </td>
                        <td className="px-3 py-1.5">
                          <Badge variant={LABEL_VARIANT[rec.label]} className="text-xs">
                            {rec.label}
                          </Badge>
                        </td>
                        <td className="px-3 py-1.5 text-muted-foreground truncate max-w-[160px]">
                          {rec.notes ?? ''}
                        </td>
                        <td className="px-2 py-1.5">
                          <div className="flex items-center justify-center gap-1">
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              onClick={() => startEdit(absoluteIdx)}
                              disabled={editingIndex !== null}
                              className="h-6 w-6 p-0 text-muted-foreground hover:text-foreground"
                              title="編集"
                            >
                              <Pencil className="size-3.5" />
                            </Button>
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              onClick={() => handleDelete(absoluteIdx)}
                              disabled={editingIndex !== null}
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

        {/* ページネーション */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {page * PAGE_SIZE + 1}〜{Math.min((page + 1) * PAGE_SIZE, records.length)} 件目 / 全
              {records.length} 件
            </span>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => p - 1)}
                disabled={page === 0}
                className="h-6 text-xs px-2"
              >
                ◀ 前へ
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => p + 1)}
                disabled={page >= totalPages - 1}
                className="h-6 text-xs px-2"
              >
                次へ ▶
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
