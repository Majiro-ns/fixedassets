'use client';

import { MainLayout } from '@/components/layout/MainLayout';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useRouter } from 'next/navigation';
import { Search, BarChart3, FileText, Database, ArrowRight, Shield } from 'lucide-react';

const FEATURES = [
  {
    icon: Search,
    title: '証券コード検索',
    desc: '4桁の証券コードから企業情報を即座に検索',
    href: '/company',
    color: 'text-blue-500',
  },
  {
    icon: BarChart3,
    title: 'ギャップ分析',
    desc: '有報を法令要件と自動照合し、過不足を検出',
    href: '/company',
    color: 'text-green-500',
  },
  {
    icon: FileText,
    title: '松竹梅提案',
    desc: '検出されたギャップに対し3水準の記載文案を生成',
    href: '/company',
    color: 'text-amber-500',
  },
  {
    icon: Database,
    title: 'EDINET連携',
    desc: '金融庁EDINETから有報PDFを直接取得・分析',
    href: '/edinet',
    color: 'text-purple-500',
  },
];

export default function HomePage() {
  const router = useRouter();

  return (
    <MainLayout>
      <div className="max-w-5xl mx-auto space-y-8">
        {/* Hero */}
        <div className="text-center space-y-4 py-8">
          <div className="flex items-center justify-center gap-2">
            <Shield className="size-8 text-primary" />
            <h1 className="text-3xl font-bold tracking-tight">開示変更分析システム</h1>
          </div>
          <p className="text-muted-foreground max-w-2xl mx-auto">
            有価証券報告書を最新法令と自動照合し、開示ギャップの検出から改善提案まで一気通貫で分析。
            M1(PDF解析) → M2(法令取得) → M3(ギャップ分析) → M4(松竹梅提案) → M5(レポート統合)
            のAIパイプラインが稼働。
          </p>
          <div className="flex flex-wrap items-center justify-center gap-2 pt-2">
            <Badge variant="secondary">Phase 2 完了</Badge>
            <Badge variant="outline">M1-M9 統合済み</Badge>
            <Badge variant="outline">272テストPASS</Badge>
          </div>
        </div>

        {/* Feature Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {FEATURES.map((f) => (
            <Card
              key={f.title}
              className="cursor-pointer hover:shadow-md transition-shadow"
              onClick={() => router.push(f.href)}
            >
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <f.icon className={`size-5 ${f.color}`} />
                  {f.title}
                </CardTitle>
                <CardDescription>{f.desc}</CardDescription>
              </CardHeader>
              <CardContent>
                <Button variant="ghost" size="sm" className="gap-1">
                  開始 <ArrowRight className="size-3" />
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Quick Start */}
        <Card>
          <CardHeader>
            <CardTitle>クイックスタート</CardTitle>
            <CardDescription>証券コードを入力するだけで分析を開始できます</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex gap-3">
              <Button size="lg" onClick={() => router.push('/company')}>
                <Search className="size-4" />
                企業検索から開始
              </Button>
              <Button variant="outline" size="lg" onClick={() => router.push('/edinet')}>
                <Database className="size-4" />
                EDINET文書ブラウザ
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* Pipeline Overview */}
        <Card>
          <CardHeader>
            <CardTitle>分析パイプライン</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              {[
                { label: 'M1', desc: 'PDF解析' },
                { label: 'M2', desc: '法令取得' },
                { label: 'M3', desc: 'ギャップ分析' },
                { label: 'M4', desc: '松竹梅提案' },
                { label: 'M5', desc: 'レポート統合' },
              ].map((step, i) => (
                <div key={step.label} className="flex items-center gap-2">
                  {i > 0 && <ArrowRight className="size-3 text-muted-foreground" />}
                  <div className="flex items-center gap-1.5 bg-muted px-3 py-1.5 rounded-full">
                    <Badge variant="default" className="text-[10px] px-1.5 py-0">
                      {step.label}
                    </Badge>
                    <span>{step.desc}</span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </MainLayout>
  );
}
