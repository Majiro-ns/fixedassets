import { Header } from './Header';

export function MainLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-background">
      <Header />
      <main id="main-content" className="max-w-5xl mx-auto px-6 py-8">{children}</main>
    </div>
  );
}
