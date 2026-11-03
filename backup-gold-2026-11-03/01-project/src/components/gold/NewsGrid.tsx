'use client'

/**
 * قاعة الأخبار الحية — AG Grid v36 (معيار البنوك)
 * cell flashing عند وصول كل تصنيف + تصنيف متوازٍ ذهبي/عام من النموذجين
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { AgGridReact } from 'ag-grid-react'
import { ModuleRegistry, AllCommunityModule, themeQuartz, type ColDef, type GridApi } from 'ag-grid-community'

ModuleRegistry.registerModules([AllCommunityModule])

export interface NewsRow {
  id: number
  title: string
  truth: string
  gold_pred?: string
  general_pred?: string
  latency_ms?: number
  state: 'pending' | 'running' | 'done' | 'error'
}

const goldTheme = themeQuartz.withParams({
  accentColor: '#f59e0b',
  backgroundColor: '#1c1814',
  foregroundColor: '#d6d3d1',
  borderColor: 'rgba(245,158,11,0.14)',
  headerBackgroundColor: '#231d16',
  headerTextColor: '#fbbf24',
  oddRowBackgroundColor: '#211c16',
  rowHoverColor: 'rgba(245,158,11,0.08)',
  fontFamily: 'IBM Plex Sans Arabic, sans-serif',
  fontSize: 13,
  headerFontSize: 12.5,
  spacing: 6,
})

const AR: Record<string, string> = {
  positive: 'إيجابي',
  negative: 'سلبي',
  neutral: 'محايد',
}

const predClass = {
  rules: {
    'gold-cell-pos': (p: { value?: string }) => p.value === 'positive',
    'gold-cell-neg': (p: { value?: string }) => p.value === 'negative',
    'gold-cell-neu': (p: { value?: string }) => p.value === 'neutral',
    'gold-cell-pending': (p: { value?: string }) => !p.value || p.value === '…',
  },
}

function predFormatter(p: { value?: string }): string {
  if (!p.value) return '…'
  return AR[p.value] ? `${AR[p.value]}` : p.value
}

const COLUMN_DEFS: ColDef<NewsRow>[] = [
  {
    field: 'title',
    headerName: 'خبر الذهب',
    flex: 3,
    minWidth: 260,
    wrapText: true,
    autoHeight: true,
    cellClass: 'leading-5',
  },
  {
    field: 'truth',
    headerName: 'الحقيقة',
    width: 92,
    ...predClass,
    valueFormatter: predFormatter,
  },
  {
    field: 'gold_pred',
    headerName: 'نموذج الذهب',
    width: 108,
    ...predClass,
    valueFormatter: predFormatter,
  },
  {
    field: 'general_pred',
    headerName: 'النموذج العام',
    width: 112,
    ...predClass,
    valueFormatter: predFormatter,
  },
  {
    field: 'latency_ms',
    headerName: 'زمن',
    width: 78,
    cellClass: 'num',
    valueFormatter: (p) => (p.value ? `${p.value}` : ''),
  },
]

export default function NewsGrid({ rows: initialRows, onRowDone, onReset, heightClass = 'h-[540px]', fill = false }: { rows: NewsRow[]; onRowDone?: (r: NewsRow) => void; onReset?: () => void; heightClass?: string; fill?: boolean }) {
  const [rows, setRows] = useState<NewsRow[]>(initialRows)
  const [running, setRunning] = useState(false)
  const apiRef = useRef<GridApi | null>(null)
  const stopRef = useRef(false)

  const flashRow = useCallback((id: number) => {
    setTimeout(() => {
      const api = apiRef.current
      if (!api) return
      const node = api.getRowNode(String(id))
      if (node) api.flashCells({ rowNodes: [node] })
    }, 30)
  }, [])

  const runAll = useCallback(async () => {
    if (running) return
    setRunning(true)
    stopRef.current = false
    const pending = rows.filter((r) => r.state !== 'done')
    for (const r of pending) {
      if (stopRef.current) break
      setRows((cur) => cur.map((x) => (x.id === r.id ? { ...x, state: 'running' } : x)))
      try {
        const resp = await fetch('/api/fingpt/predict', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: r.title, model: 'gold' }),
        })
        const j = await resp.json()
        setRows((cur) =>
          cur.map((x) =>
            x.id === r.id
              ? {
                  ...x,
                  state: resp.ok ? 'done' : 'error',
                  gold_pred: resp.ok ? j.pred : undefined,
                  general_pred: resp.ok ? j.pred_general : undefined,
                  latency_ms: resp.ok ? j.latency_ms : undefined,
                }
              : x
          )
        )
        if (resp.ok) {
          flashRow(r.id)
          onRowDone?.({ ...r, state: 'done', gold_pred: j.pred, general_pred: j.pred_general, latency_ms: j.latency_ms })
        }
      } catch {
        setRows((cur) => cur.map((x) => (x.id === r.id ? { ...x, state: 'error' } : x)))
      }
      // تحديث واجهة الجدول بعد كل صف
      await new Promise((res) => setTimeout(res, 60))
    }
    setRunning(false)
  }, [rows, running, flashRow, onRowDone])

  const stop = useCallback(() => {
    stopRef.current = true
  }, [])

  const reset = useCallback(() => {
    if (running) return
    onReset?.()
    setRows((cur) => cur.map((x) => ({ ...x, gold_pred: undefined, general_pred: undefined, latency_ms: undefined, state: 'pending' })))
  }, [running, onReset])

  // أمر لوحة الأوامر: تشغيل التحليل من أي مكان
  useEffect(() => {
    const h = () => {
      if (!running) runAll()
    }
    window.addEventListener('fingpt:analyze', h)
    return () => window.removeEventListener('fingpt:analyze', h)
  }, [running, runAll])

  const doneCount = rows.filter((r) => r.state === 'done').length
  const agreeCount = rows.filter((r) => r.state === 'done' && r.gold_pred === r.truth).length
  const generalAgree = rows.filter((r) => r.state === 'done' && r.general_pred && r.general_pred === r.truth).length

  return (
    <div className={fill ? 'flex h-full min-h-0 flex-col gap-3' : 'space-y-3'}>
      <div className="flex flex-wrap items-center gap-2">
        {!running ? (
          <button
            onClick={runAll}
            className="rounded-lg bg-amber-500 px-4 py-1.5 text-sm font-semibold text-amber-950 shadow-lg shadow-amber-500/20 transition hover:bg-amber-400"
          >
            ⚡ شغّل التحليل الحي ({rows.filter((r) => r.state !== 'done').length} متبقٍ)
          </button>
        ) : (
          <button
            onClick={stop}
            className="rounded-lg bg-red-500/90 px-4 py-1.5 text-sm font-semibold text-white transition hover:bg-red-500"
          >
            إيقاف
          </button>
        )}
        {!running && doneCount > 0 && (
          <button
            onClick={reset}
            className="rounded-lg border border-neutral-700 px-3 py-1.5 text-xs text-neutral-400 transition hover:text-neutral-200"
          >
            إعادة تعيين
          </button>
        )}
        {running && (
          <span className="flex items-center gap-1.5 text-xs text-amber-300">
            <span className="inline-block h-2 w-2 animate-ping rounded-full bg-amber-400" />
            جارٍ تحليل الأخبار مباشرة بالنموذجين…
          </span>
        )}
        {doneCount > 0 && (
          <span className="num text-xs text-neutral-400" dir="ltr">
            {agreeCount}/{doneCount} دقة الذهب {doneCount ? Math.round((agreeCount / doneCount) * 100) : 0}%
            {' · '}
            العام {Math.round((generalAgree / doneCount) * 100)}%
          </span>
        )}
      </div>
      <div dir="rtl" className={`gold-scroll min-h-0 w-full ${heightClass}`} >
        <AgGridReact
          theme={goldTheme}
          columnDefs={COLUMN_DEFS}
          rowData={rows}
          getRowId={(p) => String(p.data.id)}
          enableRtl
          pagination
          paginationPageSize={12}
          paginationPageSizeSelector={[12]}
          rowHeight={44}
          headerHeight={40}
          defaultColDef={{ resizable: true, sortable: false, suppressMovable: true }}
          onGridReady={(p) => {
            apiRef.current = p.api
          }}
        />
      </div>
    </div>
  )
}
