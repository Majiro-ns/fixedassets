import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: '固定資産AI仕分けアドバイザー | fixed-asset-agentic-pro',
  description: '仕訳・資産情報をAIが固定資産か費用かを自動判定。根拠と信頼度を可視化。',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body className="antialiased">{children}</body>
    </html>
  );
}
