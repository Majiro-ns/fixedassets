'use client';

import { useAnalysisStore } from '@/store/analysisStore';
import { Badge } from '@/components/ui/badge';
import { Clock } from 'lucide-react';
import Link from 'next/link';

export function Sidebar() {
  const history = useAnalysisStore((s) => s.history);

  return (
    <aside className="hidden lg:block w-64 border-r bg-muted/30 p-4 space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-muted-foreground flex items-center gap-1.5 mb-3">
          <Clock className="size-3.5" />
          分析履歴
        </h3>
        {history.length === 0 ? (
          <p className="text-xs text-muted-foreground">まだ分析履歴がありません</p>
        ) : (
          <ul className="space-y-2">
            {history.map((h) => (
              <li key={h.taskId}>
                <Link
                  href={`/report/${h.taskId}`}
                  className="block rounded-md border p-2 text-xs hover:bg-accent transition-colors"
                >
                  <div className="font-medium truncate">{h.companyName}</div>
                  <div className="flex items-center gap-1 mt-1 text-muted-foreground">
                    <Badge variant="outline" className="text-[10px] px-1 py-0">
                      {h.level}
                    </Badge>
                    <span>{h.date}</span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}
