'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

// Client-side alias: avoids any server-side 3xx (redirect-loop safe).
export default function HistoryAlias() {
  const router = useRouter();
  useEffect(() => {
    router.replace('/dashboard/history');
  }, [router]);
  return null;
}
