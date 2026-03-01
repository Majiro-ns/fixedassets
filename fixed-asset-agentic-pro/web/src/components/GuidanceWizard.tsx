'use client';

import { useReducer, useCallback } from 'react';
import { Loader2, AlertTriangle, RotateCcw } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { classifyAsset } from '@/lib/api';
import type { ClassifyRequest, ClassifyResponse } from '@/types/classify';
import { WizardStep1 } from '@/components/WizardStep1';
import { WizardStep2 } from '@/components/WizardStep2';
import { DiffDisplay } from '@/components/DiffDisplay';

// ─── State Machine ────────────────────────────────────────────────────

type WizardState =
  | { phase: 'step1' }
  | { phase: 'step2'; choice: 'repair' | 'upgrade' }
  | { phase: 'loading' }
  | { phase: 'diff'; nextResult: ClassifyResponse }
  | { phase: 'error'; message: string };

type WizardAction =
  | { type: 'CHOOSE_STEP1'; choice: 'repair' | 'upgrade' }
  | { type: 'LOAD' }
  | { type: 'RESOLVED'; result: ClassifyResponse }
  | { type: 'ERROR'; message: string }
  | { type: 'BACK' };

function reducer(state: WizardState, action: WizardAction): WizardState {
  switch (action.type) {
    case 'CHOOSE_STEP1':
      return { phase: 'step2', choice: action.choice };
    case 'LOAD':
      return { phase: 'loading' };
    case 'RESOLVED':
      return { phase: 'diff', nextResult: action.result };
    case 'ERROR':
      return { phase: 'error', message: action.message };
    case 'BACK':
      if (state.phase === 'step2') return { phase: 'step1' };
      if (state.phase === 'error') return { phase: 'step1' };
      return state;
    default:
      return state;
  }
}

// ─── Props ────────────────────────────────────────────────────────────

interface GuidanceWizardProps {
  /** Stage 0 の GUIDANCE 判定結果 */
  stage0Result: ClassifyResponse;
  /** 初回送信リクエスト（再判定に answers を付けて再送する） */
  originalRequest: ClassifyRequest;
  /** answers 付き再判定が完了したときに呼ばれるコールバック */
  onResolved: (result: ClassifyResponse) => void;
}

// ─── GuidanceWizard ───────────────────────────────────────────────────

export function GuidanceWizard({ stage0Result, originalRequest, onResolved }: GuidanceWizardProps) {
  const [state, dispatch] = useReducer(reducer, { phase: 'step1' });

  const handleStep2Choose = useCallback(
    async (answers: Record<string, string>) => {
      dispatch({ type: 'LOAD' });
      try {
        const result = await classifyAsset({ ...originalRequest, answers });
        dispatch({ type: 'RESOLVED', result });
        onResolved(result);
      } catch (err) {
        dispatch({
          type: 'ERROR',
          message: err instanceof Error ? err.message : '再判定中にエラーが発生しました',
        });
      }
    },
    [originalRequest, onResolved],
  );

  // ── Step 1 ────────────────────────────────────────────────────────
  if (state.phase === 'step1') {
    return (
      <WizardStep1
        missingFields={stage0Result.missing_fields}
        whyMissing={stage0Result.why_missing_matters}
        onChoose={(choice) => dispatch({ type: 'CHOOSE_STEP1', choice })}
      />
    );
  }

  // ── Step 2 ────────────────────────────────────────────────────────
  if (state.phase === 'step2') {
    return (
      <WizardStep2
        choice={state.choice}
        onChoose={handleStep2Choose}
        onBack={() => dispatch({ type: 'BACK' })}
      />
    );
  }

  // ── Loading ───────────────────────────────────────────────────────
  if (state.phase === 'loading') {
    return (
      <Card className="border-yellow-300 bg-yellow-50 dark:bg-yellow-950/20">
        <CardContent className="flex items-center justify-center gap-3 py-10 text-yellow-700">
          <Loader2 className="size-6 animate-spin" />
          <span className="text-sm font-medium">AIが再判定中です…</span>
        </CardContent>
      </Card>
    );
  }

  // ── Diff ──────────────────────────────────────────────────────────
  if (state.phase === 'diff') {
    return <DiffDisplay prevResult={stage0Result} nextResult={state.nextResult} />;
  }

  // ── Error ─────────────────────────────────────────────────────────
  if (state.phase === 'error') {
    return (
      <div className="space-y-3">
        <Alert variant="destructive">
          <AlertTriangle className="size-4" />
          <AlertTitle>再判定でエラーが発生しました</AlertTitle>
          <AlertDescription>{state.message}</AlertDescription>
        </Alert>
        <Button
          variant="outline"
          size="sm"
          onClick={() => dispatch({ type: 'BACK' })}
          className="gap-1.5"
        >
          <RotateCcw className="size-3.5" />
          やり直す
        </Button>
      </div>
    );
  }

  return null;
}
