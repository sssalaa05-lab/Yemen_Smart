import type { Metadata } from 'next';
import { Inter, JetBrains_Mono } from 'next/font/google';
import './globals.css';
import { Providers } from './providers';

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  display: 'swap',
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-mono',
  display: 'swap',
});

// Render every page per-request so browsers/gateways NEVER cache HTML.
// This yields `Cache-Control: no-store` by default and prevents the
// cached-307 redirect-loop class of bugs behind preview gateways.
export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'Nexus Trader',
  description: 'AI-Powered Multi-Agent Trading Terminal',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body
        className={`${inter.variable} ${jetbrainsMono.variable} font-sans antialiased`}
        style={{ background: 'var(--bg-primary)' }}
      >
        <Providers>
          <div className="relative min-h-screen bg-matrix">
            {children}
          </div>
        </Providers>
      </body>
    </html>
  );
}
