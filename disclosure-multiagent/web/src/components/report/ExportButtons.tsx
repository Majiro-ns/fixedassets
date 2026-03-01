'use client';

import { Button } from '@/components/ui/button';
import { Download, Copy, Check } from 'lucide-react';
import { useState } from 'react';

interface Props {
  markdown: string;
  companyName: string;
}

export function ExportButtons({ markdown, companyName }: Props) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(markdown);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownloadMd = () => {
    const blob = new Blob([markdown], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `report_${companyName}_${new Date().toISOString().slice(0, 10)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex items-center gap-2">
      <Button variant="outline" size="sm" onClick={handleCopy}>
        {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
        {copied ? 'コピー済み' : 'コピー'}
      </Button>
      <Button variant="outline" size="sm" onClick={handleDownloadMd}>
        <Download className="size-3" />
        Markdown
      </Button>
    </div>
  );
}
