'use client';

import type { ProposalSet } from '@/types';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

interface Props {
  proposals: ProposalSet[];
}

const LEVEL_CONFIG = {
  matsu: { label: '松 (詳細)', color: 'text-green-600' },
  take: { label: '竹 (標準)', color: 'text-blue-600' },
  ume: { label: '梅 (簡潔)', color: 'text-amber-600' },
};

export function ProposalCard({ proposals }: Props) {
  if (proposals.length === 0) {
    return <p className="text-sm text-muted-foreground">提案なし（ギャップ未検出）</p>;
  }

  return (
    <div className="space-y-4">
      {proposals.map((ps) => (
        <Card key={ps.gap_id}>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">{ps.disclosure_item}</CardTitle>
            <CardDescription className="text-xs">
              {ps.gap_id} | {ps.reference_law_id}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Tabs defaultValue="take">
              <TabsList>
                <TabsTrigger value="matsu">松</TabsTrigger>
                <TabsTrigger value="take">竹</TabsTrigger>
                <TabsTrigger value="ume">梅</TabsTrigger>
              </TabsList>
              {(['matsu', 'take', 'ume'] as const).map((level) => {
                const proposal = ps[level];
                const config = LEVEL_CONFIG[level];
                return (
                  <TabsContent key={level} value={level}>
                    <div className="rounded-md border p-3 space-y-2">
                      <div className="flex items-center gap-2">
                        <span className={`text-xs font-semibold ${config.color}`}>
                          {config.label}
                        </span>
                        <Badge variant="outline" className="text-[10px]">
                          {proposal.char_count}文字
                        </Badge>
                        <Badge
                          variant={proposal.status === 'pass' ? 'secondary' : 'destructive'}
                          className="text-[10px]"
                        >
                          {proposal.status}
                        </Badge>
                      </div>
                      <p className="text-sm leading-relaxed whitespace-pre-wrap">{proposal.text}</p>
                    </div>
                  </TabsContent>
                );
              })}
            </Tabs>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
