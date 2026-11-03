'use client'

/**
 * رسم شموع احترافي بمحرك TradingView Lightweight Charts v5
 * (نفس محرك منصة TradingView — 45KB — شموع بسلاسة 60fps)
 */
import { useEffect, useRef, useState } from 'react'
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  ColorType,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type Time,
} from 'lightweight-charts'

export interface Candle {
  time: string
  open: number
  high: number
  low: number
  close: number
}

const PERIODS = [
  { key: '3m', label: '3 أشهر', days: 66 },
  { key: '6m', label: '6 أشهر', days: 132 },
  { key: '1y', label: 'سنة', days: 252 },
  { key: '3y', label: '3 سنوات', days: 756 },
  { key: 'all', label: 'الكل (5 سنوات)', days: 99999 },
] as const

type PeriodKey = (typeof PERIODS)[number]['key']

function ema(values: number[], period: number): (number | null)[] {
  const k = 2 / (period + 1)
  const out: (number | null)[] = []
  let prev: number | null = null
  values.forEach((v, i) => {
    if (i < period - 1) {
      out.push(null)
      return
    }
    if (prev === null) {
      const seed = values.slice(0, period).reduce((a, b) => a + b, 0) / period
      prev = seed
    } else {
      prev = v * k + prev * (1 - k)
    }
    out.push(prev)
  })
  return out
}

export default function PriceChart({ candles, heightClass = 'h-[380px] w-full sm:h-[420px]', fill = false }: { candles: Candle[]; heightClass?: string; fill?: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const emaRef = useRef<ISeriesApi<'Line'> | null>(null)
  const [period, setPeriod] = useState<PeriodKey>('1y')
  const [showEma, setShowEma] = useState(true)
  const [hover, setHover] = useState<Candle | null>(null)

  useEffect(() => {
    emaRef.current?.applyOptions({ visible: showEma })
  }, [showEma])

  // إنشاء الرسم مرة واحدة
  useEffect(() => {
    if (!ref.current) return
    const chart = createChart(ref.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#a8a29e',
        fontFamily: 'IBM Plex Sans Arabic, IBM Plex Mono, sans-serif',
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: 'rgba(245,158,11,0.05)' },
        horzLines: { color: 'rgba(245,158,11,0.07)' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: 'rgba(245,158,11,0.4)', labelBackgroundColor: '#b45309' },
        horzLine: { color: 'rgba(245,158,11,0.4)', labelBackgroundColor: '#b45309' },
      },
      rightPriceScale: { borderColor: 'rgba(245,158,11,0.15)' },
      timeScale: { borderColor: 'rgba(245,158,11,0.15)', rightOffset: 4 },
    })
    const candle = chart.addSeries(CandlestickSeries, {
      upColor: '#f59e0b',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#fbbf24',
      wickDownColor: '#f87171',
      priceFormat: { type: 'price', precision: 1, minMove: 0.1 },
    })
    const emaLine = chart.addSeries(LineSeries, {
      color: '#38bdf8',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    chart.subscribeCrosshairMove((param) => {
      const t = param.time as string | undefined
      if (!t || !param.point) {
        setHover(null)
        return
      }
      const d = param.seriesData.get(candle) as CandlestickData<Time> | undefined
      if (d) setHover({ time: t, open: d.open, high: d.high, low: d.low, close: d.close })
    })
    chartRef.current = chart
    candleRef.current = candle
    emaRef.current = emaLine
    return () => {
      chart.remove()
      chartRef.current = null
    }
  }, [])

  // تحديث البيانات حسب الفترة
  useEffect(() => {
    const chart = chartRef.current
    const candle = candleRef.current
    const emaLine = emaRef.current
    if (!chart || !candle || !emaLine) return
    const days = PERIODS.find((p) => p.key === period)?.days ?? 252
    const slice = candles.slice(-days)
    candle.setData(slice as unknown as CandlestickData<Time>[])
    const closes = slice.map((c) => c.close)
    const emaVals = ema(closes, 50)
    emaLine.setData(
      slice
        .map((c, i) => ({ time: c.time as Time, value: emaVals[i] }))
        .filter((x): x is { time: Time; value: number } => x.value !== null)
    )
    chart.timeScale().fitContent()
  }, [candles, period])

  const last = candles[candles.length - 1]
  const prev = candles[candles.length - 2]
  const up = last && prev && last.close >= prev.close

  return (
    <div className={fill ? 'flex h-full min-h-0 flex-col gap-3' : 'space-y-3'}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-baseline gap-3">
          {hover ? (
            <div className="num flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-neutral-400" dir="ltr">
              <span>{hover.time}</span>
              <span>O <b className="text-neutral-200">{hover.open.toLocaleString('en-US')}</b></span>
              <span>H <b className="text-amber-400">{hover.high.toLocaleString('en-US')}</b></span>
              <span>L <b className="text-red-400">{hover.low.toLocaleString('en-US')}</b></span>
              <span>C <b className="text-neutral-200">{hover.close.toLocaleString('en-US')}</b></span>
            </div>
          ) : (
            last && (
              <div className="num flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-neutral-400" dir="ltr">
                <span>{last.time}</span>
                <span className="text-neutral-200">${last.close.toLocaleString('en-US')}</span>
                <span className={up ? 'text-emerald-400' : 'text-red-400'}>
                  {up ? '▲' : '▼'} {prev ? Math.abs(last.close - prev.close).toFixed(1) : '—'} $
                </span>
              </div>
            )
          )}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            onClick={() => setShowEma((v) => !v)}
            className={`rounded-full px-2.5 py-1 text-[11px] transition-colors ${showEma ? 'bg-sky-500/20 text-sky-300 ring-1 ring-sky-500/40' : 'text-neutral-500 ring-1 ring-neutral-700 hover:text-neutral-300'}`}
          >
            EMA 50
          </button>
          {PERIODS.map((p) => (
            <button
              key={p.key}
              onClick={() => setPeriod(p.key)}
              className={`rounded-full px-2.5 py-1 text-[11px] transition-colors ${
                period === p.key
                  ? 'bg-amber-500/20 text-amber-300 ring-1 ring-amber-500/50'
                  : 'text-neutral-500 ring-1 ring-neutral-700 hover:text-neutral-300'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
      <div ref={ref} className={heightClass} />
    </div>
  )
}
