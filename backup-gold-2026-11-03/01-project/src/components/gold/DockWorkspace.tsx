'use client'

/**
 * وضع Dock — rc-dock: نوافذ طرفية قابلة للرسو والتعويم والتحجيم مثل بيئات Bloomberg/IDE
 * اسحب أي تبويب من شريطه وأفلته في أي حافة، أو عوّمه كنافذة حرة — والترتيب يُحفظ تلقائياً
 */
import { useCallback, useMemo, useState } from 'react'
import DockLayout from 'rc-dock'
import type { LayoutData, TabData } from 'rc-dock/es/DockData'
import 'rc-dock/dist/rc-dock.css'
import 'rc-dock/dist/rc-dock-dark.css'
import { Badge } from '@/components/ui/badge'
import PriceChart, { type Candle } from './PriceChart'
import SignalsRoom, { type SentimentScore } from './SignalsRoom'
import NewsGrid, { type NewsRow } from './NewsGrid'

export interface TrendInfo {
  dir: 'up' | 'down' | 'flat'
  s20: number
  s50: number
  offHigh: number
  offLow: number
  chg20: number
  pos: number
  last: number
  smaGap: number
}

interface DockWorkspaceProps {
  candles: Candle[]
  sentiment: SentimentScore | null
  newsRows: NewsRow[]
  onRowDone?: (r: NewsRow) => void
  onReset?: () => void
  trend: TrendInfo | null
}

const STORAGE_KEY = 'fingpt-dock-layout'

const DEFAULT_LAYOUT: LayoutData = {
  dockbox: {
    mode: 'horizontal',
    children: [
      {
        mode: 'vertical',
        children: [
          { id: 'p-chart', tabs: [{ id: 'dock-chart' }], size: 60 },
          { id: 'p-news', tabs: [{ id: 'dock-news' }], size: 40 },
        ],
      },
      {
        mode: 'vertical',
        children: [
          { id: 'p-signals', tabs: [{ id: 'dock-signals' }, { id: 'dock-stats' }], size: 100 },
        ],
      },
    ],
  },
}

export default function DockWorkspace({ candles, sentiment, newsRows, onRowDone, onReset, trend }: DockWorkspaceProps) {
  // استرجاع ترتيب النوافذ المحفوظ (يُنشأ افتراضياً عند أول زيارة)
  const [initialLayout] = useState<LayoutData>(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (raw) {
        const parsed = JSON.parse(raw) as LayoutData
        if (parsed?.dockbox?.mode === 'horizontal' || parsed?.dockbox?.mode === 'vertical') return parsed
      }
    } catch { /* تخطيط افتراضي */ }
    return DEFAULT_LAYOUT
  })

  // تعريفات التبويبات — المحتوى يُبنى من الخصائص الحية (شموع/مشاعر/أخبار)
  const tabDefs = useMemo<Record<string, TabData>>(() => ({
    'dock-chart': {
      id: 'dock-chart',
      title: '🕯️ شموع الذهب',
      cached: true,
      content: () => (
        <div dir="rtl" className="h-full overflow-hidden p-2">
          <PriceChart candles={candles} fill heightClass="min-h-[160px] flex-1" />
        </div>
      ),
    },
    'dock-signals': {
      id: 'dock-signals',
      title: '🎯 غرفة الإشارات',
      cached: true,
      content: () => (
        <div dir="rtl" className="gold-scroll h-full overflow-y-auto p-2">
          <SignalsRoom candles={candles} sentiment={sentiment} />
        </div>
      ),
    },
    'dock-stats': {
      id: 'dock-stats',
      title: '🔔 مراقبة SMA20',
      cached: true,
      content: () => (
        <div dir="rtl" className="gold-scroll h-full space-y-2.5 overflow-y-auto p-3 text-xs leading-6">
          {!trend ? (
            <p className="text-neutral-500">في انتظار شموع الذهب…</p>
          ) : (
            <>
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-bold text-neutral-200">مراقبة SMA20 — تنبيه الانعكاس الدائم</span>
                <Badge
                  className={
                    trend.dir === 'up' ? 'bg-emerald-600 text-white' : trend.dir === 'down' ? 'bg-red-500 text-white' : 'bg-neutral-500 text-white'
                  }
                >
                  {trend.dir === 'up' ? 'صاعد ▲' : trend.dir === 'down' ? 'هابط ▼' : 'عرضي ↔'}
                </Badge>
              </div>
              {trend.dir === 'down' && trend.last > trend.s20 ? (
                <div className="rounded-md border border-amber-400/50 bg-amber-400/10 p-2 font-semibold text-amber-200">
                  ⚡ التنبيه مُفعَّل: السعر كسر SMA20 صعوداً — إشارة انعكاس مبكرة
                </div>
              ) : (
                <div className="rounded-md border border-neutral-700/60 bg-neutral-900/50 p-2 text-neutral-400">
                  التنبيه ينطلق عند الإغلاق فوق <b className="num text-amber-300" dir="ltr">${trend.s20.toFixed(0)}</b>
                  {' '}— الفارق الحالي <b className="num" dir="ltr">{trend.smaGap >= 0 ? '+' : ''}{trend.smaGap.toFixed(1)}%</b>
                </div>
              )}
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-neutral-400">
                <span>SMA20 <b className="num text-amber-300" dir="ltr">{trend.s20.toFixed(0)}</b></span>
                <span>SMA50 <b className="num text-amber-300" dir="ltr">{trend.s50.toFixed(0)}</b></span>
                <span>عن قمة السنة <b className="num text-red-400" dir="ltr">{trend.offHigh.toFixed(1)}%</b></span>
                <span>عن قاع السنة <b className="num text-emerald-400" dir="ltr">+{trend.offLow.toFixed(1)}%</b></span>
                <span>آخر 20 يوماً <b className="num" dir="ltr">{trend.chg20 >= 0 ? '+' : ''}{trend.chg20.toFixed(1)}%</b></span>
                <span>موقع النطاق <b className="num text-amber-300" dir="ltr">{trend.pos.toFixed(0)}%</b></span>
              </div>
              <p className="text-[10px] text-neutral-600">المراقبة آلية تعليمية — ليست توصية استثمارية</p>
            </>
          )}
        </div>
      ),
    },
    'dock-news': {
      id: 'dock-news',
      title: '⚡ قاعة الأخبار',
      cached: true,
      content: () => (
        <div dir="rtl" className="flex h-full min-h-0 flex-col p-2">
          <NewsGrid rows={newsRows} onRowDone={onRowDone} onReset={onReset} fill heightClass="min-h-[200px] flex-1" />
        </div>
      ),
    },
  }), [candles, sentiment, newsRows, onRowDone, onReset, trend])

  // rc-dock يحفظ التخطيط بدون المحتوى — نعيد بناء المحتوى من التعريفات عند التحميل
  const loadTab = useCallback((tab: { id?: string }): TabData | undefined => (tab.id ? tabDefs[tab.id] : undefined), [tabDefs])

  const handleLayoutChange = useCallback((newLayout: { dockbox?: unknown }) => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ dockbox: newLayout.dockbox })) } catch { /* تجاهل */ }
  }, [])

  return (
    <div className="relative h-full w-full" dir="ltr">
      <DockLayout
        style={{ position: 'absolute', left: 0, top: 0, right: 0, bottom: 0 }}
        defaultLayout={initialLayout}
        loadTab={loadTab}
        onLayoutChange={handleLayoutChange}
        dropMode="edge"
      />
    </div>
  )
}
