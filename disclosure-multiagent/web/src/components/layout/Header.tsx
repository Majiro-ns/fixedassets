'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import { FileText, Search, BarChart3, Home, Database } from 'lucide-react';

const NAV_ITEMS = [
  { href: '/', label: 'ホーム', icon: Home },
  { href: '/company', label: '企業検索', icon: Search },
  { href: '/analysis', label: '分析', icon: BarChart3 },
  { href: '/edinet', label: 'EDINET', icon: Database },
];

export function Header() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-50 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="flex h-14 items-center px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2 mr-4 sm:mr-8">
          <FileText className="size-5 text-primary" />
          <span className="font-bold text-lg">開示分析</span>
        </Link>
        <nav className="flex items-center gap-1">
          {NAV_ITEMS.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className={cn(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
                pathname === href
                  ? 'bg-primary/10 text-primary'
                  : 'text-muted-foreground hover:text-foreground hover:bg-accent'
              )}
            >
              <Icon className="size-4" />
              {label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
