import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: '固定資産AI仕分けアドバイザー | fixed-asset-agentic-pro',
  description: '仕訳・資産情報をAIが固定資産か費用かを自動判定。根拠と信頼度を可視化。',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body className="antialiased">
        {/* skip-link: WCAG 2.1 SC 2.4.1 — キーボードユーザーがナビをスキップして本文へ飛べる */}
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:top-4 focus:left-4 focus:z-50 focus:rounded focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-foreground focus:shadow-lg"
        >
          メインコンテンツへスキップ
        </a>
        {children}
      </body>
    </html>
  );
}
