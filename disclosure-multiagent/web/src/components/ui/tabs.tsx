'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';

interface TabsProps {
  defaultValue: string;
  children: React.ReactNode;
  className?: string;
}

interface TabsContextType {
  value: string;
  setValue: (v: string) => void;
}

const TabsContext = React.createContext<TabsContextType>({ value: '', setValue: () => {} });

function Tabs({ defaultValue, children, className }: TabsProps) {
  const [value, setValue] = React.useState(defaultValue);
  return (
    <TabsContext.Provider value={{ value, setValue }}>
      <div className={className}>{children}</div>
    </TabsContext.Provider>
  );
}

function TabsList({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      className={cn(
        'bg-muted text-muted-foreground inline-flex h-9 w-full items-center justify-start rounded-lg p-1 gap-1',
        className
      )}
      {...props}
    />
  );
}

function TabsTrigger({
  className,
  value,
  ...props
}: React.ComponentProps<'button'> & { value: string }) {
  const ctx = React.useContext(TabsContext);
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center whitespace-nowrap rounded-md px-3 py-1 text-sm font-medium transition-all',
        ctx.value === value
          ? 'bg-background text-foreground shadow-sm'
          : 'hover:text-foreground/80',
        className
      )}
      onClick={() => ctx.setValue(value)}
      {...props}
    />
  );
}

function TabsContent({
  className,
  value,
  children,
  ...props
}: React.ComponentProps<'div'> & { value: string }) {
  const ctx = React.useContext(TabsContext);
  if (ctx.value !== value) return null;
  return (
    <div className={cn('mt-2', className)} {...props}>
      {children}
    </div>
  );
}

export { Tabs, TabsList, TabsTrigger, TabsContent };
