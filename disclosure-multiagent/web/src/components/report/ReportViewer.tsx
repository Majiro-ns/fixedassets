'use client';

interface Props {
  markdown: string;
}

export function ReportViewer({ markdown }: Props) {
  // Simple markdown rendering with basic formatting
  const lines = markdown.split('\n');

  return (
    <div className="prose prose-sm max-w-none">
      {lines.map((line, i) => {
        if (line.startsWith('# ')) {
          return (
            <h1 key={i} className="text-xl font-bold mt-6 mb-2">
              {line.slice(2)}
            </h1>
          );
        }
        if (line.startsWith('## ')) {
          return (
            <h2 key={i} className="text-lg font-semibold mt-4 mb-2 border-b pb-1">
              {line.slice(3)}
            </h2>
          );
        }
        if (line.startsWith('### ')) {
          return (
            <h3 key={i} className="text-base font-semibold mt-3 mb-1">
              {line.slice(4)}
            </h3>
          );
        }
        if (line.startsWith('- ')) {
          return (
            <li key={i} className="ml-4 text-sm">
              {line.slice(2)}
            </li>
          );
        }
        if (line.startsWith('|')) {
          return (
            <pre key={i} className="text-xs font-mono bg-muted p-0.5">
              {line}
            </pre>
          );
        }
        if (line.trim() === '') {
          return <div key={i} className="h-2" />;
        }
        return (
          <p key={i} className="text-sm leading-relaxed">
            {line}
          </p>
        );
      })}
    </div>
  );
}
