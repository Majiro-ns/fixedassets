import { MainLayout } from '@/components/layout/MainLayout';
import { Skeleton } from '@/components/ui/skeleton';

export default function Loading() {
  return (
    <MainLayout>
      <div className="max-w-5xl mx-auto space-y-8">
        <div className="space-y-4 py-8">
          <Skeleton className="h-10 w-64 mx-auto" />
          <Skeleton className="h-4 w-96 mx-auto" />
          <Skeleton className="h-4 w-80 mx-auto" />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
        <Skeleton className="h-24 w-full" />
      </div>
    </MainLayout>
  );
}
