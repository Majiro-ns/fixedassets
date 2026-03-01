'use client';

import type { PipelineStep } from '@/types';
import { cn } from '@/lib/utils';
import { CheckCircle2, Circle, Loader2, XCircle } from 'lucide-react';

interface Props {
  steps: PipelineStep[];
  currentStep: number;
}

const STEP_ICONS = {
  pending: Circle,
  running: Loader2,
  done: CheckCircle2,
  error: XCircle,
};

export function PipelineProgress({ steps, currentStep }: Props) {
  return (
    <div className="space-y-3">
      {steps.map((step, i) => {
        const Icon = STEP_ICONS[step.status];
        return (
          <div
            key={step.step}
            className={cn(
              'flex items-start gap-3 rounded-lg border p-3 transition-all',
              step.status === 'running' && 'border-primary bg-primary/5',
              step.status === 'done' && 'border-green-500/50 bg-green-50',
              step.status === 'error' && 'border-destructive/50 bg-destructive/5'
            )}
          >
            <div className="mt-0.5">
              <Icon
                className={cn(
                  'size-5',
                  step.status === 'pending' && 'text-muted-foreground',
                  step.status === 'running' && 'text-primary animate-spin',
                  step.status === 'done' && 'text-green-600',
                  step.status === 'error' && 'text-destructive'
                )}
              />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-medium text-sm">Step {step.step}</span>
                <span className="text-sm">{step.name}</span>
              </div>
              {step.detail && <p className="text-xs text-muted-foreground mt-0.5">{step.detail}</p>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
