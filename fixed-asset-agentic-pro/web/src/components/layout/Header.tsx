import { Building2 } from 'lucide-react';

export function Header() {
  return (
    <header className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="max-w-5xl mx-auto px-6 h-14 flex items-center gap-3">
        <Building2 className="size-5 text-primary" />
        <span className="font-semibold text-sm">固定資産AIアドバイザー</span>
        <span className="ml-auto text-xs text-muted-foreground">fixed-asset-agentic-pro</span>
      </div>
    </header>
  );
}
