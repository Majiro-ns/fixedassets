'use client';

import { useState, useEffect, useRef } from 'react';
import { Input } from '@/components/ui/input';
import { searchCompany } from '@/lib/api/client';
import type { CompanyInfo } from '@/types';
import { Search, Building2, Loader2 } from 'lucide-react';

interface Props {
  onSelect: (company: CompanyInfo) => void;
}

export function StockCodeInput({ onSelect }: Props) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<CompanyInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (query.length < 2) {
      setResults([]);
      setOpen(false);
      return;
    }

    timerRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const isCode = /^\d{4,5}$/.test(query);
        const resp = await searchCompany(isCode ? { sec_code: query } : { name: query });
        setResults(resp.results);
        setOpen(resp.results.length > 0);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 300);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [query]);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div ref={wrapperRef} className="relative">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
        <Input
          placeholder="証券コード (例: 7203) または企業名"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => results.length > 0 && setOpen(true)}
          className="pl-9 pr-9"
        />
        {loading && (
          <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 size-4 animate-spin text-muted-foreground" />
        )}
      </div>

      {open && (
        <div className="absolute z-50 mt-1 w-full rounded-md border bg-popover shadow-lg max-h-64 overflow-auto">
          {results.map((company) => (
            <button
              key={company.edinet_code}
              className="flex items-center gap-3 w-full px-3 py-2 text-left text-sm hover:bg-accent transition-colors"
              onClick={() => {
                onSelect(company);
                setQuery(`${company.sec_code} ${company.company_name}`);
                setOpen(false);
              }}
            >
              <Building2 className="size-4 text-muted-foreground shrink-0" />
              <div className="min-w-0">
                <div className="font-medium truncate">{company.company_name}</div>
                <div className="text-xs text-muted-foreground">
                  {company.sec_code && `${company.sec_code} | `}
                  {company.edinet_code}
                  {company.industry && ` | ${company.industry}`}
                </div>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
