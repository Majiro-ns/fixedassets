import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: '開示変更分析 | disclosure-multiagent',
  description: '有価証券報告書の法令準拠ギャップ分析 & 松竹梅提案ツール',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body className="antialiased">{children}</body>
    </html>
  );
}
