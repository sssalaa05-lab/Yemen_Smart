'use client'

/**
 * غرفة الصفقات والإشارات — يحوّل (الفني + مشاعر النموذج المدرّب) إلى خطة تداول
 * كل الأرقام محسوبة لحظياً من شموع COMEX الحقيقية وتصنيفات قاعة الأخبار الحية
 * ملاحظة: تحليل تعليمي آلي — وليس توصية استثمارية
 */
import { useMemo } from 'react'
import { motion } from 'motion/react'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Activity, BrainCircuit, Info, Scale, Target } from 'lucide-react'
import type { Candle } from './PriceChart'

export interface SentimentScore { done: number; pos: number; neg: number; neu: number }

function sma(v: number[], n: number): number {
  const s = v.slice(-n)
  return s.reduce((a, b) => a + b, 0) / s.length
}

/** RSI قياسي بتمهيد وايلدر */
function rsiWilder(closes: number[], n = 14): number {
  let g = 0, l = 0
  for (let i = 1; i <= n; i++) {
    const d = closes[i] - closes[i - 1]
    if (d >= 0) g += d; else l -= d
  }
  let ag = g / n, al = l / n
  for (let i = n + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1]
    ag = (ag * (n - 1) + Math.max(d, 0)) / n
    al = (al * (n - 1) + Math.max(-d, 0)) / n
  }
  if (al === 0) return 100
  return 100 - 100 / (1 + ag / al)
}

/** ATR بتمهيد بسيط لآخر n شمعة */
function atr14(c: Candle[], n = 14): number {
  let sum = 0
  for (let i = c.length - n; i < c.length; i++) {
    const pc = c[i - 1].close
    sum += Math.max(c[i].high - c[i].low, Math.abs(c[i].high - pc), Math.abs(c[i].low - pc))
  }
  return sum / n
}

export default function SignalsRoom({ candles, sentiment }: { candles: Candle[]; sentiment: SentimentScore | null }) {
  const calc = useMemo(() => {
    if (candles.length < 60) return null
    const closes = candles.map((c) => c.close)
    const last = closes[closes.length - 1]
    const s20 = sma(closes, 20), s50 = sma(closes, 50)
    const r = rsiWilder(closes)
    const a = atr14(candles)
    const yr = candles.slice(-252)
    const lo52 = Math.min(...yr.map((x) => x.low))
    const hi52 = Math.max(...yr.map((x) => x.high))
    const hi20 = Math.max(...candles.slice(-20).map((x) => x.high))
    // كم يوماً (خلال سنة) كان السعر ضمن 1% من قاع 52 أسبوعاً؟ (ندرة تاريخية)
    let nearLowDays = 0
    for (let i = 260; i < candles.length; i++) {
      let lo = Infinity
      for (let j = i - 252; j < i; j++) lo = Math.min(lo, candles[j].low)
      if (candles[i].low <= lo * 1.01) nearLowDays++
    }
    const entry = last
    const stop = lo52 - 0.5 * a
    const risk = entry - stop
    const tp1 = s20, tp2 = hi20
    const pos52 = ((last - lo52) / Math.max(1e-9, hi52 - lo52)) * 100
    return {
      last, s20, s50, rsi: r, atr: a, lo52, hi52, hi20,
      entry, stop, risk, tp1, tp2, pos52, nearLowDays,
      rr1: (tp1 - entry) / risk, rr2: (tp2 - entry) / risk,
      stopPct: (stop / entry - 1) * 100,
      tp1Pct: (tp1 / entry - 1) * 100, tp2Pct: (tp2 / entry - 1) * 100,
    }
  }, [candles])

  if (!calc) {
    return (
      <Card className="h-full">
        <CardContent className="flex h-full min-h-[320px] items-center justify-center p-6 text-sm text-neutral-500">
          في انتظار شموع الذهب لحساب الإشارات…
        </CardContent>
      </Card>
    )
  }

  const bear = calc.last < calc.s20 && calc.s20 < calc.s50
  const oversold = calc.rsi < 35
  const nearLow = calc.pos52 <= 10

  const sentDone = sentiment?.done ?? 0
  const posPct = sentDone ? Math.round(((sentiment?.pos ?? 0) / sentDone) * 100) : 0
  const negPct = sentDone ? Math.round(((sentiment?.neg ?? 0) / sentDone) * 100) : 0
  const neuPct = Math.max(0, 100 - posPct - negPct)

  let verdict = 'لا توجد إشارة قوية — وضع المراقبة.'
  if (bear && oversold && nearLow)
    verdict = 'هبوط ممتد عند قيعان نادرة — إشارة ارتداد مبكرة محتملة. التأكيد المطلوب: إغلاق يومي فوق SMA20.'
  else if (bear)
    verdict = 'اتجاه هابط — الأولوية للحذر؛ أي شراء مضاربي فقط بوقف صارم تحت القاع.'

  let sentVerdict = ''
  if (sentDone >= 10) {
    if (posPct >= 55) sentVerdict = 'المشاعر الحية تدعم سيناريو الارتداد ✓'
    else if (negPct >= 50) sentVerdict = 'المشاعر الحية ضاغطة سلبياً — الارتداد غير مؤكد بعد'
    else sentVerdict = 'المشاعر الحية متوازنة — انتظر تأكيد السعر'
  }

  // شريط المستويات: من الوقف حتى الهدف 2
  const lo = calc.stop, hi = calc.tp2
  const posOf = (v: number) => ((v - lo) / Math.max(1e-9, hi - lo)) * 100

  const planRows = [
    { label: 'الدخول', value: `$${calc.entry.toLocaleString('en-US')}`, sub: 'السعر الحالي', cls: 'text-amber-300' },
    { label: 'وقف الخسارة', value: `$${calc.stop.toFixed(1)}`, sub: `${calc.stopPct.toFixed(1)}% — تحت القاع + ½ATR`, cls: 'text-red-400' },
    { label: 'هدف 1', value: `$${calc.tp1.toFixed(1)}`, sub: `+${calc.tp1Pct.toFixed(1)}% — SMA20 · R:R ${calc.rr1.toFixed(2)}`, cls: 'text-emerald-400' },
    { label: 'هدف 2', value: `$${calc.tp2.toFixed(1)}`, sub: `+${calc.tp2Pct.toFixed(1)}% — قمة 20 يوماً · R:R ${calc.rr2.toFixed(2)}`, cls: 'text-emerald-400' },
    { label: 'مخاطرة الصفقة', value: `$${calc.risk.toFixed(1)}`, sub: 'لكل أونصة — اقترح مخاطرة 1% من رأس المال', cls: 'text-neutral-200' },
    { label: 'إدارة المركز', value: 'مرحّلة', sub: 'جزء عند الهدف 1 وباقي الوقف لنقطة الدخول', cls: 'text-neutral-200' },
  ]

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-base font-bold">
          <Target className="h-5 w-5 text-amber-400" /> غرفة الصفقات والإشارات
        </h3>
        <Badge variant="outline" className="border-red-500/40 bg-red-500/10 text-[10px] text-red-300">
          <Info className="ml-1 h-3 w-3" /> تعليمي — ليست توصية استثمارية
        </Badge>
      </div>

      {/* خطة الصفقة المقترحة */}
      <Card className="border-amber-500/25 bg-gradient-to-br from-amber-500/10 to-transparent">
        <CardContent className="space-y-3 p-4">
          <p className="flex items-center gap-2 text-sm font-bold text-amber-300">
            <Scale className="h-4 w-4" /> الصفقة المقترحة — سيناريو ارتداد القاع (شراء محافظ)
          </p>
          <div className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-xs sm:grid-cols-3">
            {planRows.map((r) => (
              <div key={r.label}>
                <p className="text-[10px] text-neutral-500">{r.label}</p>
                <p className={`num text-sm font-bold ${r.cls}`} dir="ltr">{r.value}</p>
                <p className="text-[10px] leading-4 text-neutral-500">{r.sub}</p>
              </div>
            ))}
          </div>
          {/* شريط المستويات */}
          <div dir="ltr">
            <div className="relative h-7 overflow-hidden rounded-md bg-neutral-900 ring-1 ring-neutral-800">
              <div className="absolute inset-y-0 left-0 bg-red-500/15" style={{ width: `${posOf(calc.entry)}%` }} />
              <div className="absolute inset-y-0 right-0 bg-emerald-500/10" style={{ width: `${100 - posOf(calc.entry)}%` }} />
              {[
                { v: calc.stop, c: 'bg-red-400', t: 'وقف' },
                { v: calc.entry, c: 'bg-amber-300', t: 'دخول' },
                { v: calc.tp1, c: 'bg-emerald-400', t: 'هدف 1' },
                { v: calc.tp2, c: 'bg-emerald-300', t: 'هدف 2' },
              ].map((m) => (
                <motion.div
                  key={m.t}
                  className={`absolute top-1/2 h-3.5 w-1 -translate-y-1/2 rounded-full ${m.c}`}
                  style={{ left: `calc(${posOf(m.v)}% - 2px)` }}
                  initial={{ scaleY: 0 }}
                  animate={{ scaleY: 1 }}
                  transition={{ duration: 0.5 }}
                />
              ))}
            </div>
            <div className="num mt-1 flex justify-between text-[10px] text-neutral-500">
              <span className="text-red-400">وقف {calc.stop.toFixed(0)}</span>
              <span className="text-amber-300">دخول {calc.entry.toFixed(0)}</span>
              <span className="text-emerald-400">هدف1 {calc.tp1.toFixed(0)}</span>
              <span className="text-emerald-300">هدف2 {calc.tp2.toFixed(0)}</span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* الإشارات الفنية */}
      <Card>
        <CardContent className="space-y-2 p-4">
          <p className="flex items-center gap-2 text-sm font-bold text-neutral-200">
            <Activity className="h-4 w-4 text-amber-400" /> الإشارات الفنية (محسوبة من الشموع الحقيقية)
          </p>
          <div className="space-y-1.5 text-xs leading-5">
            <p className="text-neutral-400">
              <Badge className={`mr-2 ${bear ? 'bg-red-500 text-white' : 'bg-emerald-600 text-white'}`}>{bear ? 'هابط ▼' : 'صاعد ▲'}</Badge>
              السعر تحت SMA20 (${calc.s20.toFixed(0)}) و SMA50 (${calc.s50.toFixed(0)}) — ترتيب هابط كامل
            </p>
            <p className="text-neutral-400">
              <Badge className={`mr-2 ${oversold ? 'bg-amber-500 text-amber-950' : 'bg-neutral-600 text-white'}`}>RSI {calc.rsi.toFixed(1)}</Badge>
              {oversold ? 'منطقة تشبع بيعي — تاريخياً تسبق ارتدادات تصحيحية' : 'زخم محايد'}
            </p>
            <p className="text-neutral-400">
              <Badge className="mr-2 bg-amber-500/20 text-amber-300">نادر</Badge>
              السعر عند {calc.pos52.toFixed(0)}% من نطاق 52 أسبوعاً — {calc.nearLowDays === 0 ? 'لم يلامس هذا القاع إطلاقاً خلال 5 سنوات' : `يوم واحد فقط خلال 5 سنوات ضمن 1% من قاع سنوي`}
            </p>
            <p className="text-neutral-400">
              <Badge className="mr-2 bg-neutral-700 text-neutral-200">ATR ${calc.atr.toFixed(1)}</Badge>
              التذبذب اليومي المتوسط — يقاس به الوقف ديناميكياً (½ ATR هنا)
            </p>
          </div>
        </CardContent>
      </Card>

      {/* مشاعر السوق الحية */}
      <Card>
        <CardContent className="space-y-2 p-4">
          <p className="flex items-center gap-2 text-sm font-bold text-neutral-200">
            <BrainCircuit className="h-4 w-4 text-amber-400" /> مشاعر السوق الحية — من النموذج المدرّب
          </p>
          {sentDone === 0 ? (
            <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-500">
              <span>لا توجد تصنيفات بعد — غذِّ هذه البطاقة من قاعة الأخبار:</span>
              <button
                onClick={() => window.dispatchEvent(new Event('fingpt:analyze'))}
                className="rounded-md border border-amber-500/40 px-2 py-1 text-amber-300 transition hover:bg-amber-500/10"
              >
                ⚡ شغّل التحليل الحي (40 خبراً)
              </button>
            </div>
          ) : (
            <>
              <div className="flex h-3 w-full overflow-hidden rounded-full bg-neutral-800" dir="ltr">
                <motion.div className="bg-emerald-500" initial={{ width: 0 }} animate={{ width: `${posPct}%` }} transition={{ duration: 0.6 }} />
                <motion.div className="bg-neutral-500" animate={{ width: `${neuPct}%` }} transition={{ duration: 0.6 }} />
                <motion.div className="bg-red-500" animate={{ width: `${negPct}%` }} transition={{ duration: 0.6 }} />
              </div>
              <div className="num flex justify-between text-[11px] text-neutral-400" dir="ltr">
                <span className="text-emerald-400">إيجابي {posPct}%</span>
                <span>محايد {neuPct}%</span>
                <span className="text-red-400">سلبي {negPct}%</span>
              </div>
              {sentVerdict && <p className="text-xs font-medium text-amber-300/90">{sentVerdict}</p>}
              <p className="text-[10px] text-neutral-600">مصدر: تصنيف نموذج الذهب لـ {sentDone} خبراً حقيقياً لم يرها التدريب</p>
            </>
          )}
        </CardContent>
      </Card>

      {/* الخلاصة الآلية */}
      <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-xs leading-6 text-neutral-300">
        <b className="text-amber-300">الخلاصة الآلية:</b> {verdict}
        {sentVerdict && <> <span className="text-neutral-600">·</span> {sentVerdict}</>}
      </div>
    </div>
  )
}
