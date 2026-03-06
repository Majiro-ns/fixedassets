import Link from 'next/link';
import { Building2, CalendarDays } from 'lucide-react';

export function Header() {
  return (
    <header className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="max-w-5xl mx-auto px-6 h-14 flex items-center gap-3">
        <Link href="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
          <Building2 className="size-5 text-primary" />
          <span className="font-semibold text-sm">固定資産AIアドバイザー</span>
        </Link>
        <nav className="flex items-center gap-1 ml-4" aria-label="メインナビゲーション">
          <Link
            href="/calendar"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            data-testid="nav-link-calendar"
          >
            <CalendarDays className="size-4" />
            カレンダー
          </Link>
        </nav>
        <span className="ml-auto text-xs text-muted-foreground">fixed-asset-agentic-pro</span>
      </div>
    </header>
  );
}
