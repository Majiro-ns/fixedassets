"use client";

import { useRouter } from "next/navigation";

const FEATURES = [
  {
    title: "年末調整計算",
    desc: "給与収入・社会保険料・各種控除を入力するだけで源泉徴収税額を自動計算",
    href: "/calculate",
    color: "text-blue-600",
    icon: "¥",
  },
  {
    title: "配偶者・扶養控除",
    desc: "配偶者控除・扶養控除を考慮した正確な税額計算",
    href: "/calculate",
    color: "text-green-600",
    icon: "👨‍👩‍👧",
  },
  {
    title: "生命保険料控除",
    desc: "新契約・旧契約の生命保険料控除を自動計算",
    href: "/calculate",
    color: "text-orange-600",
    icon: "🛡",
  },
  {
    title: "住宅ローン控除",
    desc: "住宅ローン年末残高・入居年に基づく税額控除を計算",
    href: "/calculate",
    color: "text-purple-600",
    icon: "🏠",
  },
  {
    title: "CSV インポート",
    desc: "源泉徴収票 CSV を一括取込。教師データとして登録しAIアシストを強化",
    href: "/import",
    color: "text-teal-600",
    icon: "📂",
  },
];

const PIPELINE = [
  { label: "入力", desc: "給与・控除" },
  { label: "計算", desc: "税額算出" },
  { label: "確認", desc: "控除内訳" },
  { label: "出力", desc: "源泉徴収票" },
];

export default function HomePage() {
  const router = useRouter();

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xl font-bold">nencho</span>
            <span className="text-xs bg-secondary text-secondary-foreground px-2 py-0.5 rounded-full">
              年末調整AI
            </span>
          </div>
          <nav className="flex gap-4 text-sm text-muted-foreground">
            <button
              onClick={() => router.push("/calculate")}
              className="hover:text-foreground transition-colors"
            >
              計算開始
            </button>
            <button
              onClick={() => router.push("/import")}
              className="hover:text-foreground transition-colors"
            >
              CSV取込
            </button>
          </nav>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-12 space-y-12">
        {/* ヒーローセクション */}
        <section className="text-center space-y-4 py-8">
          <div className="flex items-center justify-center gap-3">
            <span className="text-4xl">📋</span>
            <h1 className="text-3xl font-bold tracking-tight">年末調整計算システム</h1>
          </div>
          <p className="text-muted-foreground max-w-2xl mx-auto text-lg">
            給与所得・各種控除から源泉徴収税額を自動計算。
            令和7年税制改正（基礎控除上乗せ特例）に完全対応。
          </p>
          <div className="flex items-center justify-center gap-2 pt-2 flex-wrap">
            <span className="text-xs bg-blue-100 text-blue-700 px-3 py-1 rounded-full">令和7年改正対応</span>
            <span className="text-xs bg-green-100 text-green-700 px-3 py-1 rounded-full">国税庁データ準拠</span>
            <span className="text-xs bg-purple-100 text-purple-700 px-3 py-1 rounded-full">全控除対応</span>
          </div>
          <div className="flex justify-center gap-3 pt-4">
            <button
              onClick={() => router.push("/calculate")}
              className="px-6 py-3 bg-primary text-primary-foreground rounded-lg font-medium hover:opacity-90 transition-opacity"
            >
              今すぐ計算する
            </button>
          </div>
        </section>

        {/* 機能カード */}
        <section>
          <h2 className="text-xl font-semibold mb-4">主な機能</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {FEATURES.map((f) => (
              <div
                key={f.title}
                onClick={() => router.push(f.href)}
                className="border border-border rounded-lg p-5 cursor-pointer hover:shadow-md transition-shadow bg-card"
              >
                <div className="flex items-start gap-3">
                  <span className={`text-2xl ${f.color} font-bold`}>{f.icon}</span>
                  <div>
                    <h3 className="font-semibold text-card-foreground">{f.title}</h3>
                    <p className="text-sm text-muted-foreground mt-1">{f.desc}</p>
                  </div>
                </div>
                <div className="mt-3">
                  <span className="text-xs text-primary hover:underline">計算を開始 →</span>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* パイプライン概要 */}
        <section className="border border-border rounded-lg p-6 bg-card">
          <h2 className="font-semibold mb-4">処理フロー</h2>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            {PIPELINE.map((step, i) => (
              <div key={step.label} className="flex items-center gap-2">
                {i > 0 && <span className="text-muted-foreground">→</span>}
                <div className="flex items-center gap-1.5 bg-muted px-3 py-1.5 rounded-full">
                  <span className="text-xs font-bold bg-primary text-primary-foreground px-1.5 py-0.5 rounded-full">
                    {step.label}
                  </span>
                  <span className="text-muted-foreground">{step.desc}</span>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* クイックスタート */}
        <section className="border border-border rounded-lg p-6 bg-card">
          <h2 className="font-semibold mb-2">クイックスタート</h2>
          <p className="text-sm text-muted-foreground mb-4">
            給与収入と社会保険料を入力するだけで、令和7年分の概算税額をすぐに確認できます
          </p>
          <button
            onClick={() => router.push("/calculate")}
            className="px-5 py-2.5 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:opacity-90 transition-opacity"
          >
            年末調整を計算する →
          </button>
        </section>
      </main>
    </div>
  );
}
