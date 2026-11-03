'use client'

/**
 * شبكة KPI قابلة للسحب وإعادة الترتيب — react-grid-layout v2 (hook-based)
 * الترتيب يُحفظ تلقائياً في localStorage · الشبكة داخل حاوية LTR لسلامة السحب، والمحتوى RTL
 */
import { useState } from 'react'
import { GripVertical } from 'lucide-react'
import {
  ResponsiveGridLayout,
  useContainerWidth,
  type Layout,
  type ResponsiveLayouts,
} from 'react-grid-layout'
import 'react-grid-layout/css/styles.css'

export interface KpiItem { id: string; el: React.ReactNode }

type BP = 'lg' | 'md' | 'sm'

const DEFAULT_LAYOUTS: ResponsiveLayouts<BP> = {
  lg: [
    { i: 'kpi-price', x: 0, y: 0, w: 1, h: 1 },
    { i: 'kpi-range', x: 1, y: 0, w: 1, h: 1 },
    { i: 'kpi-acc', x: 2, y: 0, w: 1, h: 1 },
    { i: 'kpi-engine', x: 3, y: 0, w: 1, h: 1 },
  ],
  md: [
    { i: 'kpi-price', x: 0, y: 0, w: 1, h: 1 },
    { i: 'kpi-range', x: 1, y: 0, w: 1, h: 1 },
    { i: 'kpi-acc', x: 0, y: 1, w: 1, h: 1 },
    { i: 'kpi-engine', x: 1, y: 1, w: 1, h: 1 },
  ],
  sm: [
    { i: 'kpi-price', x: 0, y: 0, w: 1, h: 1 },
    { i: 'kpi-range', x: 0, y: 1, w: 1, h: 1 },
    { i: 'kpi-acc', x: 0, y: 2, w: 1, h: 1 },
    { i: 'kpi-engine', x: 0, y: 3, w: 1, h: 1 },
  ],
}

const STORAGE_KEY = 'fingpt-kpi-layouts'

export default function KpiGrid({ items }: { items: KpiItem[] }) {
  const { width, containerRef, mounted } = useContainerWidth({ measureBeforeMount: true })

  // قراءة الترتيب المحفوظ مرة واحدة عند أول عرض (بدون effect)
  const [layouts] = useState<ResponsiveLayouts<BP>>(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (raw) {
        const p = JSON.parse(raw) as ResponsiveLayouts<BP>
        const ids = items.map((i) => i.id).sort().join(',')
        const same = (arr?: Layout) => arr?.length === items.length && arr.map((l) => l.i).sort().join(',') === ids
        if (same(p.lg) && same(p.md) && same(p.sm)) return p
      }
    } catch { /* تخطيط افتراضي */ }
    return DEFAULT_LAYOUTS
  })

  const saveLayouts = (all: ResponsiveLayouts<BP>) => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(all)) } catch { /* تجاهل */ }
  }

  return (
    <div dir="ltr" ref={containerRef}>
      {!mounted ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {items.map((i) => <div key={i.id}>{i.el}</div>)}
        </div>
      ) : (
        <ResponsiveGridLayout
          width={width}
          layouts={layouts}
          breakpoints={{ lg: 1024, md: 700, sm: 0 }}
          cols={{ lg: 4, md: 2, sm: 1 }}
          rowHeight={158}
          margin={[12, 12]}
          containerPadding={[0, 0]}
          resizeConfig={{ enabled: false }}
          onLayoutChange={(_, all) => saveLayouts(all)}
        >
          {items.map((i) => (
            <div key={i.id} className="relative h-full cursor-grab active:cursor-grabbing" dir="rtl">
              <GripVertical className="absolute left-1 top-1 z-10 h-3.5 w-3.5 text-neutral-600" />
              {i.el}
            </div>
          ))}
        </ResponsiveGridLayout>
      )}
    </div>
  )
}
