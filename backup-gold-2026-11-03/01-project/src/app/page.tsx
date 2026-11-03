'use client'

import { useCallback, useEffect, useMemo, useRef, useState, type ComponentType } from 'react'
import dynamic from 'next/dynamic'
import Image from 'next/image'
import { motion } from 'motion/react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { CountUp } from '@/components/gold/CountUp'
import CommandPalette, { type PaletteAction } from '@/components/gold/CommandPalette'
import type { Candle } from '@/components/gold/PriceChart'
import type { NewsRow } from '@/components/gold/NewsGrid'
import type { SentimentScore } from '@/components/gold/SignalsRoom'
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels'
import { Tabs, TabList, Tab } from 'react-aria-components'
import { Allotment } from 'allotment'
import 'allotment/dist/style.css'
import {
  GitBranch, Database, CheckCircle2, Loader2, XCircle, Circle,
  Activity, RefreshCw, FlaskConical, Server, TrendingUp, Sparkles, Coins,
  CandlestickChart, Newspaper, Gauge, Command as CommandIcon, Zap, MoveHorizontal,
  BellRing, LayoutGrid,
} from 'lucide-react'

// محرك TradingView + AG Grid تعملان في المتصفح فقط
const PriceChart = dynamic(() => import('@/components/gold/PriceChart'), { ssr: false })
const NewsGrid = dynamic(() => import('@/components/gold/NewsGrid'), { ssr: false })
const SignalsRoom = dynamic(() => import('@/components/gold/SignalsRoom'), { ssr: false })
const KpiGrid = dynamic(() => import('@/components/gold/KpiGrid'), { ssr: false })
const DockWorkspace = dynamic(() => import('@/components/gold/DockWorkspace'), { ssr: false })
const YemenSmartPanel = dynamic(() => import('@/components/gold/YemenSmartPanel'), { ssr: false })

interface Progress {
  stage?: string; status?: string; detail?: string
  train_n?: number; test_n?: number
  trainable_params?: number; total_params?: number
  step?: number; loss?: number; elapsed_s?: number
  acc_baseline?: number; acc_final?: number
  adapter_dir?: string; adapter_files?: number; adapter_mb?: number
}
interface Sample { input: string; gold: string; pred: string; ok: boolean }
interface Results {
  base_model: string; template: string
  lora: { r: number; alpha: number; targets: string[]; trainable_params: number; total_params: number }
  adapter?: { saved: boolean; dir: string; files: number; size_mb: number; instruction: string }
  datasets: { train: string; test: string }
  training: { steps: number; effective_batch: number; lr: number; seconds: number; loss_curve: number[] }
  eval: { n: number; acc_before: number; acc_after: number }
  samples_before: Sample[]; samples_after: Sample[]
  hardware: { device: string; threads: number }
}
interface Verified { date: string; pytest: string; forex: string; packages_ok: string; torch: string; transformers: string }
interface Repo { url: string; commit: string; exists: boolean }
interface SysInfo { platform: string; arch: string; cpus: number; ram_gb: number; node: string }
interface GoldProgress {
  stage?: string; status?: string; detail?: string
  train_n?: number; test_n?: number
  step?: number; loss?: number; elapsed_s?: number
  base_acc_on_gold?: number
  adapter_mb?: number
  acc_base?: number; acc_general?: number; acc_gold?: number
}
interface GoldResults {
  base_model: string; keywords: string
  train_n: number; test_n: number; label_dist: Record<string, number>
  training: { steps: number; effective_batch: number; lr: number; seconds: number; loss_curve: number[] }
  eval: { n: number; acc_base: number; acc_general: number; acc_gold: number }
  samples: { input: string; gold: string; pred: string; ok: boolean }[]
  adapter: { saved: boolean; dir: string; size_mb: number }
  price: { symbol: string; currency: string; latest: number; prev: number | null; series: number[] } | null
}
interface GoldTestRow { id: number; input: string; output: string }
interface ApiData {
  progress: Progress | null; results: Results | null; verified: Verified | null
  goldProgress: GoldProgress | null; goldResults: GoldResults | null
  goldTest: GoldTestRow[] | null
  repo: Repo | null; sys: SysInfo | null; ts: number
}
interface GoldDailySummary {
  symbol: string; name: string; last: number; prev_close: number
  chg_1d_pct: number; chg_1y_pct: number; high_52w: number; low_52w: number
  currency: string; count: number; first_date: string; last_date: string
}
interface GoldDaily { summary: GoldDailySummary; candles: Candle[] }
interface PredResult { pred: string; raw?: string; latency_ms: number; adapter?: string; pred_general?: string }

const EXAMPLES = [
  { label: 'ذهب يسجل قمة تاريخية', text: 'Gold prices surge to a record high as central banks keep buying bullion.' },
  { label: 'الدولار يقمع الذهب', text: 'Gold prices slip as the dollar strengthens after stronger-than-expected US jobs data.' },
  { label: 'ترقب قرارات الفيدرالي', text: 'Spot gold trades flat in quiet dealing ahead of the Federal Reserve minutes release.' },
  { label: 'شركة مناجم تتفوق', text: 'Barrick Gold beats quarterly production estimates and raises full-year guidance.' },
]

function predBadge(p?: string): string {
  if (p === 'positive') return 'bg-emerald-600 text-white'
  if (p === 'negative') return 'bg-red-500 text-white'
  return 'bg-neutral-500 text-white'
}
function predLabel(p?: string): string {
  if (p === 'positive') return 'إيجابي'
  if (p === 'negative') return 'سلبي'
  if (p === 'neutral') return 'محايد'
  return p || '—'
}

const STEPS = [
  { key: 'download_data', label: 'تحميل بيانات FinGPT (sentiment-train + sentiment-cls)' },
  { key: 'load_model', label: 'تحميل النموذج الأساسي + محوّل LoRA' },
  { key: 'baseline_eval', label: 'تقييم أساسي قبل الضبط الدقيق' },
  { key: 'training', label: 'تدريب LoRA على بيانات المشاعر المالية' },
  { key: 'export_adapter', label: 'تصدير أوزان LoRA لخدمة الاستدلال الحيّ' },
  { key: 'finetuned_eval', label: 'تقييم نهائي بعد الضبط الدقيق' },
]

const GOLD_STEPS = [
  { key: 'filter_data', label: 'تصفية أخبار الذهب من بيانات FinGPT (gold / XAU / GLD / GDX / bullion)' },
  { key: 'load_model', label: 'تحميل النموذج العام + إضافة محوّل ذهب جديد (تدريب متتابع)' },
  { key: 'gold_training', label: 'تدريب محوّل الذهب على أسطر الذهب فقط' },
  { key: 'save_adapter', label: 'حفظ محوّل الذهب (adapter_gold)' },
  { key: 'eval_gold', label: 'مقارنة ثلاثية على أخبار الذهب: أساسي × عام × ذهب' },
  { key: 'gold_price', label: 'جلب سعر الذهب الحقيقي (عقود COMEX)' },
]

// مساحات العمل — كل مساحة تجمع أدوات مرتبطة في شاشة واحدة بلا تمرير طويل
// التبويبات عبر React Aria (أقوى دعم accessibility + RTL)
type WsKey = 'market' | 'news' | 'model' | 'training' | 'dock'
const WORKSPACES: { id: WsKey; label: string; icon: ComponentType<{ className?: string }> }[] = [
  { id: 'market', label: 'السوق', icon: CandlestickChart },
  { id: 'news', label: 'الأخبار', icon: Newspaper },
  { id: 'model', label: 'النموذج', icon: Gauge },
  { id: 'training', label: 'التدريب', icon: Database },
  { id: 'dock', label: 'وضع Dock', icon: LayoutGrid },
]
const WS_OF: Record<string, WsKey> = { chart: 'market', news: 'news', live: 'news', model: 'model', pipeline: 'training' }

function fmtParams(n?: number): string {
  if (!n) return '—'
  if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B'
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M'
  return String(n)
}
function pct(a?: number): string {
  return a != null ? (a * 100).toFixed(1) + '%' : '—'
}

function StageIcon({ state }: { state: 'running' | 'done' | 'pending' | 'error' }) {
  if (state === 'done') return <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-500" />
  if (state === 'running') return <Loader2 className="h-5 w-5 shrink-0 animate-spin text-amber-400" />
  if (state === 'error') return <XCircle className="h-5 w-5 shrink-0 text-red-500" />
  return <Circle className="h-5 w-5 shrink-0 text-neutral-600" />
}

function Bar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-sm">
        <span className="text-neutral-400">{label}</span>
        <span className="num font-semibold" dir="ltr">{pct(value)}</span>
      </div>
      <div className="h-3 w-full overflow-hidden rounded-full bg-neutral-800">
        <motion.div
          className={`h-full rounded-full ${color}`}
          initial={{ width: 0 }}
          whileInView={{ width: `${Math.max(2, value * 100)}%` }}
          viewport={{ once: true }}
          transition={{ duration: 1.1, ease: [0.16, 1, 0.3, 1] }}
        />
      </div>
    </div>
  )
}

function LossCurve({ curve, color = '#f59e0b' }: { curve: number[]; color?: string }) {
  if (!curve || curve.length < 2) return null
  const pts = curve.filter((_, i) => i % Math.max(1, Math.ceil(curve.length / 40)) === 0 || i === curve.length - 1)
  const max = Math.max(...pts), min = Math.min(...pts)
  const rng = max - min || 1
  const coords = pts.map((v, i) => `${(i / (pts.length - 1)) * 100},${28 - ((v - min) / rng) * 24}`).join(' ')
  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-sm text-neutral-400">
        <TrendingUp className="h-4 w-4" style={{ color }} /> منحنى خسارة التدريب
      </div>
      <svg viewBox="0 0 100 30" preserveAspectRatio="none" className="h-24 w-full rounded-md bg-neutral-900/60 ring-1 ring-amber-500/10" role="img" aria-label="منحنى الخسارة">
        <polyline points={coords} fill="none" stroke={color} strokeWidth="1.2" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="num mt-1 flex justify-between text-xs text-neutral-500" dir="ltr">
        <span>{pts[0].toFixed(3)}</span>
        <span>{pts[pts.length - 1].toFixed(3)}</span>
      </div>
    </div>
  )
}

const reveal = {
  initial: { opacity: 0, y: 26 },
  whileInView: { opacity: 1, y: 0 },
  viewport: { once: true, margin: '-40px' },
  transition: { duration: 0.55, ease: [0.16, 1, 0.3, 1] as const },
}

export default function Home() {
  const [data, setData] = useState<ApiData | null>(null)
  const [goldDaily, setGoldDaily] = useState<GoldDaily | null>(null)
  const [text, setText] = useState('')
  const [pred, setPred] = useState<PredResult | null>(null)
  const [predBusy, setPredBusy] = useState(false)
  const [predErr, setPredErr] = useState('')
  const [modelSel, setModelSel] = useState<'general' | 'gold'>('gold')
  const [newsRows, setNewsRows] = useState<NewsRow[]>([])
  const newsInit = useRef(false)
  const [sent, setSent] = useState<SentimentScore>({ done: 0, pos: 0, neg: 0, neu: 0 })
  const [isDesktop, setIsDesktop] = useState(true)
  const [tab, setTab] = useState<WsKey>('market')
  const [dockOpened, setDockOpened] = useState(false)
  const [dockKey, setDockKey] = useState(0)
  const [showSmart, setShowSmart] = useState(false)

  // فتح لوحة يمن سمارت مباشرة عند وجود ?smart=1 في الرابط
  useEffect(() => {
    try {
      if (new URLSearchParams(window.location.search).has('smart')) setShowSmart(true)
    } catch { /* تجاهل */ }
  }, [])

  // وضع الطرفية على الشاشات الكبيرة: ألواح قابلة للتقسيم (react-resizable-panels)
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1024px)')
    const h = () => setIsDesktop(mq.matches)
    h()
    mq.addEventListener('change', h)
    return () => mq.removeEventListener('change', h)
  }, [])

  // كل تصنيف حي من قاعة الأخبار يغذّي غرفة الإشارات
  const onNewsRowDone = useCallback((r: NewsRow) => {
    setSent((s) => ({
      done: s.done + 1,
      pos: s.pos + (r.gold_pred === 'positive' ? 1 : 0),
      neg: s.neg + (r.gold_pred === 'negative' ? 1 : 0),
      neu: s.neu + (r.gold_pred === 'neutral' ? 1 : 0),
    }))
  }, [])
  const onNewsReset = useCallback(() => setSent({ done: 0, pos: 0, neg: 0, neu: 0 }), [])

  const selectTab = useCallback((k: string | number) => {
    const key = String(k) as WsKey
    setTab(key)
    if (key === 'dock') setDockOpened(true)
  }, [])

  // زر التحليل في غرفة الإشارات يعمل من أي مساحة عمل: ننتقل إلى الأخبار أولاً ثم نشغّل التحليل
  const lastAutoAnalyze = useRef(0)
  useEffect(() => {
    const h = () => {
      const now = Date.now()
      if (now - lastAutoAnalyze.current < 500) return
      lastAutoAnalyze.current = now
      setTab('news')
      setTimeout(() => window.dispatchEvent(new Event('fingpt:analyze')), 260)
    }
    window.addEventListener('fingpt:analyze', h)
    return () => window.removeEventListener('fingpt:analyze', h)
  }, [])

  const runPredict = useCallback(async (t: string, model: 'general' | 'gold' = 'gold') => {
    const input = t.trim()
    if (!input) return
    setPredBusy(true); setPredErr(''); setPred(null)
    try {
      const r = await fetch('/api/fingpt/predict', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: input, model }),
      })
      const j = await r.json()
      if (!r.ok) setPredErr(j?.error || 'فشل التحليل')
      else setPred(j)
    } catch { setPredErr('تعذّر الاتصال بالخادم') }
    finally { setPredBusy(false) }
  }, [])

  const load = useCallback(async () => {
    try {
      const r = await fetch('/api/fingpt', { cache: 'no-store' })
      setData(await r.json())
    } catch { /* retry on next tick */ }
  }, [])

  const loadPrices = useCallback(async () => {
    try {
      const r = await fetch('/gold/gold_daily.json', { cache: 'no-store' })
      if (r.ok) setGoldDaily(await r.json())
    } catch { /* keep old data */ }
  }, [])

  useEffect(() => {
    const t = setTimeout(load, 0)
    const id = setInterval(load, 4000)
    loadPrices()
    return () => { clearTimeout(t); clearInterval(id) }
  }, [load, loadPrices])

  // قاعة الأخبار: تجهيز الصفوف مرة واحدة من مجموعة التقييم الحقيقية
  useEffect(() => {
    if (newsInit.current || !data?.goldTest?.length) return
    newsInit.current = true
    setNewsRows(data.goldTest.map((r) => ({ id: r.id, title: r.input, truth: r.output, state: 'pending' as const })))
  }, [data])

  const p = data?.progress ?? null
  const res = data?.results ?? null
  const gp = data?.goldProgress ?? null
  const gr = data?.goldResults ?? null
  const stageIdx = STEPS.findIndex(s => s.key === p?.stage)
  const errored = p?.stage === 'error'
  const gStageIdx = GOLD_STEPS.findIndex(s => s.key === gp?.stage)
  const gErrored = gp?.stage === 'error'

  const sum = goldDaily?.summary
  const lastPrice = sum?.last ?? gr?.price?.latest ?? null
  const chgDay = sum?.chg_1d_pct ?? (gr?.price?.latest != null && gr?.price?.prev != null
    ? (gr.price.latest / gr.price.prev - 1) * 100 : null)

  // حساب اتجاه الذهب من الشموع الحقيقية: SMA20/SMA50 + الموقع من نطاق 52 أسبوعاً
  const trend = useMemo(() => {
    const cs = goldDaily?.candles ?? []
    if (cs.length < 60) return null
    const closes = cs.map((c) => c.close)
    const last = closes[closes.length - 1]
    const sma = (n: number) => closes.slice(-n).reduce((a, b) => a + b, 0) / n
    const s20 = sma(20), s50 = sma(50)
    const yr = cs.slice(-252)
    const hi = Math.max(...yr.map((c) => c.high))
    const lo = Math.min(...yr.map((c) => c.low))
    const chg = (n: number) => (last / closes[closes.length - 1 - n] - 1) * 100
    let dir: 'up' | 'down' | 'flat' = 'flat'
    if (last > s20 && s20 > s50) dir = 'up'
    else if (last < s20 && s20 < s50) dir = 'down'
    return {
      dir, s20, s50,
      last,
      smaGap: (last / s20 - 1) * 100,
      offHigh: (last / hi - 1) * 100,
      offLow: (last / lo - 1) * 100,
      chg20: chg(20),
      pos: ((last - lo) / Math.max(1e-9, hi - lo)) * 100,
      lo,
    }
  }, [goldDaily])

  const go = useCallback((id: string) => {
    const ws = WS_OF[id]
    if (ws) setTab(ws)
    // ننتظر تحميل مساحة العمل الجديدة ثم نمرر إليها
    setTimeout(() => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 90)
  }, [])

  const chartCard = (
    <Card className="h-full">
      <CardContent className="p-3 sm:p-4">
        {goldDaily?.candles?.length ? (
          <PriceChart candles={goldDaily.candles} />
        ) : (
          <div className="flex h-[380px] items-center justify-center text-sm text-neutral-500">
            <Loader2 className="ml-2 h-4 w-4 animate-spin" /> جارٍ تحميل الشموع…
          </div>
        )}
        <p className="num mt-2 text-[11px] text-neutral-500" dir="ltr">
          {sum ? `${sum.count} candles · ${sum.first_date} → ${sum.last_date} · Yahoo Finance (real COMEX futures)` : ''}
        </p>
      </CardContent>
    </Card>
  )

  // بطاقة التجربة الحية — تُعرض داخل تقسيم Allortment في مساحة الأخبار (أو مكدسة على الجوال)
  const liveCard = (
    <section id="live" aria-label="تجربة حية" className="scroll-mt-20">
      <Card className="border-amber-500/20">
        <CardContent className="space-y-3 p-4 sm:p-6">
          <h3 className="flex items-center gap-2 text-base font-bold">
            <Sparkles className="h-5 w-5 text-amber-400" /> التجربة الحية — اكتب خبراً واختبر النموذجين
          </h3>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-neutral-400">المحوّل:</span>
            <Tabs
              selectedKey={modelSel}
              onSelectionChange={(k) => setModelSel(k as 'gold' | 'general')}
              aria-label="اختيار المحوّل"
              className="outline-none"
            >
              <TabList aria-label="المحوّلات المتاحة" className="flex flex-wrap gap-2 outline-none">
                <Tab
                  id="gold"
                  isDisabled={predBusy || !gr}
                  className={({ isSelected }) =>
                    `cursor-pointer rounded-full px-3 py-1 text-xs transition-colors outline-none data-[disabled]:opacity-50 data-[focused]:ring-1 data-[focused]:ring-amber-500/60 ${isSelected ? 'bg-amber-500 text-amber-950' : 'border border-neutral-700 text-neutral-400 hover:text-neutral-200'}`
                  }
                >
                  🥇 نموذج الذهب — مع مقارنة
                </Tab>
                <Tab
                  id="general"
                  isDisabled={predBusy}
                  className={({ isSelected }) =>
                    `cursor-pointer rounded-full px-3 py-1 text-xs transition-colors outline-none data-[disabled]:opacity-50 data-[focused]:ring-1 data-[focused]:ring-amber-500/60 ${isSelected ? 'bg-neutral-500 text-white' : 'border border-neutral-700 text-neutral-400 hover:text-neutral-200'}`
                  }
                >
                  النموذج العام
                </Tab>
              </TabList>
            </Tabs>
          </div>
          <Textarea
            dir="auto" rows={3} value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="مثال: Gold rallies as the Fed signals rate cuts and the dollar weakens…"
            className="border-neutral-700 bg-neutral-900/60"
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button
              onClick={() => runPredict(text, modelSel)}
              disabled={predBusy || !text.trim()}
              className="bg-amber-500 text-amber-950 shadow-lg shadow-amber-500/25 hover:bg-amber-400"
            >
              {predBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              {predBusy ? 'جارٍ التحليل…' : 'حلّل المشاعر'}
            </Button>
            {EXAMPLES.map((ex) => (
              <button
                key={ex.label}
                onClick={() => { setText(ex.text); runPredict(ex.text, modelSel) }}
                disabled={predBusy}
                className="rounded-full border border-neutral-700 px-3 py-1 text-xs text-neutral-400 transition-colors hover:border-amber-500/40 hover:text-amber-300 disabled:opacity-50"
              >
                {ex.label}
              </button>
            ))}
          </div>
          <p className="text-xs text-neutral-500">أول تحليل قد يستغرق حتى دقيقة (تحميل النموذج على CPU) — التالية خلال ثوانٍ.</p>
          {predErr && <p className="rounded-md bg-red-950/60 p-3 text-sm text-red-400">{predErr}</p>}
          {pred && (
            <div className="rounded-md border border-amber-500/20 bg-neutral-900/60 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm text-neutral-400">التصنيف:</span>
                {modelSel === 'gold' && pred.pred_general ? (
                  <>
                    <Badge className={predBadge(pred.pred)}>🥇 الذهب: {predLabel(pred.pred)}</Badge>
                    <span className="text-xs text-neutral-500">مقابل العام:</span>
                    <Badge className={predBadge(pred.pred_general)}>{predLabel(pred.pred_general)}</Badge>
                  </>
                ) : (
                  <Badge className={predBadge(pred.pred)}>{predLabel(pred.pred)}</Badge>
                )}
                <span className="num text-xs text-neutral-500" dir="ltr">{pred.latency_ms} ms</span>
              </div>
              {pred.raw && <p className="num mt-2 break-all text-xs text-neutral-600" dir="ltr">raw: {pred.raw}</p>}
            </div>
          )}
        </CardContent>
      </Card>
    </section>
  )

  const actions: PaletteAction[] = useMemo(() => [
    { id: 'nav-chart', group: 'تنقّل', label: 'الرسم البياني — شموع الذهب', hint: '#chart', run: () => go('chart') },
    { id: 'nav-signals', group: 'تنقّل', label: 'غرفة الصفقات والإشارات', hint: 'دخول/وقف/أهداف', run: () => go('chart') },
    { id: 'nav-news', group: 'تنقّل', label: 'قاعة الأخبار الحية', hint: '#news', run: () => go('news') },
    { id: 'nav-model', group: 'تنقّل', label: 'نموذج الذهب — المقارنة الثلاثية', hint: '#model', run: () => go('model') },
    { id: 'nav-pipeline', group: 'تنقّل', label: 'مسار التدريب', hint: '#pipeline', run: () => go('pipeline') },
    { id: 'nav-live', group: 'تنقّل', label: 'التجربة الحية', hint: '#live', run: () => go('live') },
    { id: 'ws-dock', group: 'تنقّل', label: 'وضع Dock — نوافذ قابلة للرسو والتعويم', hint: 'rc-dock', run: () => selectTab('dock') },
    { id: 'nav-smart', group: 'تنقّل', label: 'لوحة يمن سمارت الذهبية — إدارة التداول', hint: 'MT5', run: () => setShowSmart(true) },
    { id: 'act-analyze', group: 'إجراءات', label: 'تشغيل التحليل الحي لقاعة الأخبار', hint: '40 خبراً', run: () => { go('news'); setTimeout(() => window.dispatchEvent(new Event('fingpt:analyze')), 120) } },
    { id: 'act-refresh', group: 'إجراءات', label: 'تحديث البيانات الآن', hint: 'F5 منطقي', run: () => { load(); loadPrices() } },
    ...EXAMPLES.map((ex, i) => ({
      id: `ex-${i}`, group: 'أمثلة ذهبية' as const, label: ex.label, hint: 'تحليل فوري',
      run: () => { go('live'); setText(ex.text); runPredict(ex.text, 'gold') },
    })),
  ], [go, load, loadPrices, runPredict, selectTab, setShowSmart])

  // لوحة يمن سمارت تُعرض كواجهة كاملة داخل نفس المسار (بدون تنقل لمسار آخر)
  if (showSmart) {
    return <YemenSmartPanel onBack={() => setShowSmart(false)} />
  }

  return (
    <div dir="rtl" className="relative flex min-h-screen flex-col bg-background text-foreground">
      {/* توهج ذهبي علوي */}
      <div className="pointer-events-none fixed inset-x-0 top-0 z-0 h-80 bg-[radial-gradient(ellipse_at_top,rgba(245,158,11,0.12),transparent_62%)]" />

      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-amber-500/15 bg-background/80 backdrop-blur-md">
        <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center justify-between gap-2 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="relative h-10 w-10 shrink-0 overflow-hidden rounded-xl ring-1 ring-amber-400/50 shadow-lg shadow-amber-500/25">
              <Image src="/yemen/emblem.png" alt="شعار يمن سمارت — باب اليمن الذهبي" fill sizes="40px" className="object-cover" />
            </div>
            <div>
              <h1 className="text-lg font-bold leading-tight sm:text-xl">
                FinGPT <span className="gold-text">Gold</span> — طرفية سوق الذهب
              </h1>
              <p className="text-xs text-neutral-400">نموذج مالي متخصص بأخبار الذهب · دقة 92.5% على بيانات لم يرها التدريب</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="gap-1 border-amber-500/40 bg-amber-500/10 text-amber-300">
              <Activity className="h-3 w-3" /> بث حي كل 4 ثوانٍ
            </Badge>
            <button
              onClick={() => setShowSmart(true)}
              className="hidden items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-2.5 py-1.5 text-xs font-semibold text-amber-300 transition hover:bg-amber-500/20 sm:flex"
            >
              🥇 يمن سمارت
            </button>
            <button
              onClick={() => window.dispatchEvent(new Event('fingpt:palette'))}
              className="flex items-center gap-2 rounded-lg border border-neutral-700 px-2.5 py-1.5 text-xs text-neutral-400 transition hover:border-amber-500/40 hover:text-amber-300"
            >
              <CommandIcon className="h-3.5 w-3.5" /> لوحة الأوامر
              <kbd className="num rounded border border-neutral-700 px-1 text-[10px]" dir="ltr">⌘K</kbd>
            </button>
          </div>
        </div>
      </header>

      <main className="relative z-10 mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">

        {/* شريط مساحات العمل — تبويبات RTL (React Aria Tabs) */}
        <div className="sticky top-[63px] z-40 -mx-4 mb-5 border-b border-amber-500/10 bg-background/85 px-4 py-2 backdrop-blur-md sm:-mx-6 sm:px-6">
          <Tabs selectedKey={tab} onSelectionChange={selectTab} aria-label="مساحات العمل">
            <TabList aria-label="مساحات العمل" className="flex flex-wrap items-center gap-1">
              {WORKSPACES.map((w) => (
                <Tab
                  key={w.id}
                  id={w.id}
                  className={({ isSelected }) =>
                    `flex cursor-pointer items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition-colors outline-none data-[focused]:ring-1 data-[focused]:ring-amber-500/60 ${
                      isSelected
                        ? 'bg-gradient-to-b from-amber-400 to-amber-600 font-bold text-amber-950 shadow-md shadow-amber-500/25'
                        : 'text-neutral-400 hover:bg-neutral-900 hover:text-amber-200'
                    }`
                  }
                >
                  <w.icon className="h-4 w-4" />
                  {w.label}
                </Tab>
              ))}
            </TabList>
          </Tabs>
        </div>

        {/* ===== مساحة السوق: مؤشرات قابلة للسحب + شموع وغرفة إشارات بألواح قابلة للتقسيم ===== */}
        {tab === 'market' && (
        <div className="space-y-8">

        {/* KPIs */}
        <motion.section {...reveal} aria-label="مؤشرات السوق والنموذج">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-neutral-500">
            <MoveHorizontal className="h-3.5 w-3.5" /> بطاقات قابلة للسحب وإعادة الترتيب (تُحفظ تلقائياً) — react-grid-layout
          </div>
          <KpiGrid
            items={[
              {
                id: 'kpi-price',
                el: <Card className="h-full border-amber-500/20 bg-gradient-to-br from-amber-500/10 to-transparent">
                  <CardContent className="p-4">
                    <p className="text-xs text-neutral-400">الذهب — عقود COMEX (GC=F)</p>
                    <div className="mt-1 flex items-baseline gap-2">
                      {lastPrice != null ? (
                        <CountUp value={lastPrice} decimals={1} prefix="$" className="text-3xl font-bold text-amber-300" />
                      ) : (
                        <span className="num text-3xl text-neutral-500">…</span>
                      )}
                      {chgDay != null && (
                        <Badge className={chgDay >= 0 ? 'bg-emerald-600 text-white' : 'bg-red-500 text-white'} dir="ltr">
                          {chgDay >= 0 ? '+' : ''}{chgDay.toFixed(2)}%
                        </Badge>
                      )}
                    </div>
                    <p className="num mt-1 text-[11px] text-neutral-500" dir="ltr">{sum?.last_date || 'Yahoo Finance'} · real data</p>
                  </CardContent>
                </Card>,
              },
              {
                id: 'kpi-range',
                el: <Card className="h-full">
                  <CardContent className="p-4">
                    <p className="text-xs text-neutral-400">نطاق 52 أسبوعاً</p>
                    <div className="mt-1 flex items-baseline gap-3">
                      <span className="num text-lg font-bold text-neutral-200" dir="ltr">${(sum?.low_52w ?? 0).toLocaleString('en-US')}</span>
                      <span className="text-xs text-neutral-500">→</span>
                      <span className="num text-lg font-bold text-amber-300" dir="ltr">${(sum?.high_52w ?? 0).toLocaleString('en-US')}</span>
                    </div>
                    {sum && (
                      <div className="mt-2 h-1.5 w-full rounded-full bg-neutral-800">
                        <div
                          className="h-full rounded-full bg-gradient-to-r from-amber-600 to-amber-300"
                          style={{ width: `${Math.max(2, Math.min(100, ((sum.last - sum.low_52w) / Math.max(1e-9, sum.high_52w - sum.low_52w)) * 100))}%` }}
                        />
                      </div>
                    )}
                    <p className="mt-1 text-[11px] text-neutral-500">تغير سنوي: <span className={`num ${(sum?.chg_1y_pct ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`} dir="ltr">{sum ? `${sum.chg_1y_pct >= 0 ? '+' : ''}${sum.chg_1y_pct}%` : '—'}</span></p>
                  </CardContent>
                </Card>,
              },
              {
                id: 'kpi-acc',
                el: <Card className="h-full">
                  <CardContent className="p-4">
                    <p className="text-xs text-neutral-400">دقة نموذج الذهب (اختبار محجوب)</p>
                    <div className="mt-1 flex items-baseline gap-2">
                      {gr ? (
                        <CountUp value={gr.eval.acc_gold * 100} decimals={1} suffix="%" className="text-3xl font-bold text-amber-300" />
                      ) : <span className="num text-3xl text-neutral-500">…</span>}
                      <span className="text-xs text-neutral-500">مقابل</span>
                    </div>
                    <div className="num mt-1 flex gap-3 text-[11px] text-neutral-400" dir="ltr">
                      <span>base {gr ? pct(gr.eval.acc_base) : '—'}</span>
                      <span>general {gr ? pct(gr.eval.acc_general) : '—'}</span>
                    </div>
                  </CardContent>
                </Card>,
              },
              {
                id: 'kpi-engine',
                el: <Card className="h-full">
                  <CardContent className="p-4">
                    <p className="text-xs text-neutral-400">محرك الاستدلال الحي</p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <Badge className="bg-amber-500 text-amber-950">نموذج الذهب ✓</Badge>
                      <Badge className="bg-neutral-600 text-white">العام ✓</Badge>
                    </div>
                    <p className="mt-2 text-[11px] text-neutral-500">Qwen2.5-0.5B + محوّلا LoRA · CPU</p>
                    <Button size="sm" variant="outline" className="mt-2 h-7 border-amber-500/40 text-xs text-amber-300 hover:bg-amber-500/10" onClick={() => go('live')}>
                      جرّبه الآن <Zap className="h-3 w-3" />
                    </Button>
                  </CardContent>
                </Card>,
              },
            ]}
          />
        </motion.section>

        {/* Chart */}
        <motion.section {...reveal} id="chart" aria-label="الرسم البياني" className="scroll-mt-20">
          <h2 className="mb-3 flex items-center gap-2 text-lg font-bold">
            <CandlestickChart className="h-5 w-5 text-amber-400" />
            شموع الذهب — محرك <span className="gold-text">TradingView Lightweight Charts v5</span>
          </h2>
          {trend && (
            <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-lg border border-amber-500/15 bg-amber-500/5 px-3 py-2 text-xs">
              <Badge className={trend.dir === 'up' ? 'bg-emerald-600 text-white' : trend.dir === 'down' ? 'bg-red-500 text-white' : 'bg-neutral-500 text-white'}>
                الاتجاه العام: {trend.dir === 'up' ? 'صاعد ▲' : trend.dir === 'down' ? 'هابط ▼' : 'عرضي ↔'}
              </Badge>
              <span className="text-neutral-400">آخر 20 يوماً: <b className={`num ${trend.chg20 >= 0 ? 'text-emerald-400' : 'text-red-400'}`} dir="ltr">{trend.chg20 >= 0 ? '+' : ''}{trend.chg20.toFixed(1)}%</b></span>
              <span className="text-neutral-400">عن قمة السنة: <b className={`num ${trend.offHigh >= 0 ? 'text-emerald-400' : 'text-red-400'}`} dir="ltr">{trend.offHigh.toFixed(1)}%</b></span>
              <span className="text-neutral-400">عن قاع السنة: <b className={`num ${trend.offLow >= 0 ? 'text-emerald-400' : 'text-red-400'}`} dir="ltr">{trend.offLow >= 0 ? '+' : ''}{trend.offLow.toFixed(1)}%</b></span>
              <span className="text-neutral-400">السعر عند <b className="num text-amber-300" dir="ltr">{trend.pos.toFixed(0)}%</b> من نطاق 52 أسبوعاً</span>
              <span className="text-neutral-500">SMA20 <b className="num" dir="ltr">{trend.s20.toFixed(0)}</b> · SMA50 <b className="num" dir="ltr">{trend.s50.toFixed(0)}</b></span>
            </div>
          )}
          {/* تنبيه SMA20 الدائم — يُثبّت بعد انعكاس مبكر */}
          {trend && (
            <div
              className={`mb-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border px-3 py-2 text-xs ${
                trend.dir === 'down' && trend.last > trend.s20
                  ? 'border-amber-400/60 bg-amber-400/10 text-amber-200 shadow-md shadow-amber-500/10'
                  : 'border-neutral-700/60 bg-neutral-900/40 text-neutral-500'
              }`}
              role="status"
            >
              <BellRing className="h-3.5 w-3.5 shrink-0" />
              {trend.dir === 'down' && trend.last > trend.s20 ? (
                <span><b>تنبيه SMA20 مُفعّل:</b> السعر كسر SMA20 صعوداً — إشارة انعكاس مبكرة محتملة للاتجاه الهابط</span>
              ) : (
                <span>
                  مراقبة SMA20 نشطة — التنبيه ينطلق عند الإغلاق فوق <b className="num text-amber-300" dir="ltr">${trend.s20.toFixed(0)}</b>
                  {' '}(الفارق الحالي <b className="num" dir="ltr">{trend.smaGap >= 0 ? '+' : ''}{trend.smaGap.toFixed(1)}%</b>)
                </span>
              )}
            </div>
          )}
          {isDesktop ? (
            <PanelGroup direction="horizontal" autoSaveId="fingpt-gold-split" className="items-stretch">
              <Panel defaultSize={59} minSize={35}>
                {chartCard}
              </Panel>
              <PanelResizeHandle className="group mx-1 flex w-2 cursor-col-resize items-center justify-center rounded-lg bg-neutral-800/60 transition hover:bg-amber-500/40">
                <div className="h-12 w-1 rounded-full bg-neutral-600 transition group-hover:bg-amber-400" />
              </PanelResizeHandle>
              <Panel defaultSize={41} minSize={26}>
                <SignalsRoom candles={goldDaily?.candles ?? []} sentiment={sent} />
              </Panel>
            </PanelGroup>
          ) : (
            <div className="space-y-5">
              {chartCard}
              <SignalsRoom candles={goldDaily?.candles ?? []} sentiment={sent} />
            </div>
          )}
        </motion.section>
        </div>
        )}

        {/* ===== مساحة الأخبار: تقسيم رأسي قابل للسحب (Allotment بأسلوب IDE) + التجربة الحية ===== */}
        {tab === 'news' && (
          <div className="space-y-4">
            <h2 className="flex flex-wrap items-center gap-2 text-lg font-bold">
              <Newspaper className="h-5 w-5 text-amber-400" />
              قاعة الأخبار الحية — <span className="gold-text">AG Grid v36</span> + تصنيف لحظي بالنموذجين
              {isDesktop && <span className="text-xs font-normal text-neutral-500">· الفاصل الأفقي قابل للسحب (Allotment)</span>}
            </h2>
            <p className="text-xs text-neutral-500">
              40 خبراً ذهبياً حقيقياً من مجموعة التقييم (لم يرها التدريب) — كل صف يُصنَّف مباشرة بكل من نموذج الذهب والنموذج العام، مع وميض الخلية عند وصول النتيجة
            </p>
            {isDesktop ? (
              <div className="h-[calc(100vh-235px)] min-h-[600px]">
                <Allotment vertical defaultSizes={[3, 2]}>
                  <div className="h-full min-h-0">
                    {newsRows.length ? (
                      <NewsGrid rows={newsRows} onRowDone={onNewsRowDone} onReset={onNewsReset} fill heightClass="min-h-[240px] flex-1" />
                    ) : (
                      <div className="flex h-40 items-center justify-center text-sm text-neutral-500">
                        <Loader2 className="ml-2 h-4 w-4 animate-spin" /> جارٍ تجهيز قاعة الأخبار…
                      </div>
                    )}
                  </div>
                  <div className="gold-scroll h-full min-h-0 overflow-y-auto pl-1">
                    {liveCard}
                  </div>
                </Allotment>
              </div>
            ) : (
              <div className="space-y-5">
                {newsRows.length ? (
                  <NewsGrid rows={newsRows} onRowDone={onNewsRowDone} onReset={onNewsReset} />
                ) : (
                  <div className="flex h-40 items-center justify-center text-sm text-neutral-500">
                    <Loader2 className="ml-2 h-4 w-4 animate-spin" /> جارٍ تجهيز قاعة الأخبار…
                  </div>
                )}
                {liveCard}
              </div>
            )}
          </div>
        )}

        {/* ===== مساحة النموذج: المقارنة الثلاثية + البيئة ===== */}
        {tab === 'model' && (
        <div className="space-y-8">

        {/* Gold model comparison */}
        <motion.section {...reveal} id="model" aria-label="نموذج الذهب" className="scroll-mt-20">
          <h2 className="mb-3 flex items-center gap-2 text-lg font-bold">
            <Gauge className="h-5 w-5 text-amber-400" />
            نموذج الذهب المتخصص — <span className="gold-text">التخصص يرفع الدقة</span>
          </h2>
          {gr ? (
            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-base">دقة تصنيف أخبار الذهب ({gr.eval.n} مثالاً محجوباً)</CardTitle></CardHeader>
                <CardContent className="space-y-4">
                  <Bar label="النموذج الأساسي (بدون ضبط)" value={gr.eval.acc_base} color="bg-neutral-500" />
                  <Bar label="النموذج العام (بيانات FinGPT الكاملة)" value={gr.eval.acc_general} color="bg-amber-400" />
                  <Bar label="نموذج الذهب (تخصص متتابع)" value={gr.eval.acc_gold} color="bg-gradient-to-r from-amber-600 to-amber-300" />
                  <p className="text-xs text-neutral-500">
                    تدريب متتابع على {gr.train_n} سطراً ذهبياً ({gr.keywords}) · محوّل {gr.adapter.size_mb} MB · تصنيفات الاختبار: {Object.entries(gr.label_dist).map(([k, v]) => `${k}=${v}`).join('، ')}
                  </p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-base">تفاصيل تخصص الذهب</CardTitle></CardHeader>
                <CardContent className="space-y-3 text-sm text-neutral-400">
                  <LossCurve curve={gr.training.loss_curve} />
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                    <span>خطوات: <b className="num" dir="ltr">{gr.training.steps}</b></span>
                    <span>حزمة فعّالة: <b className="num" dir="ltr">{gr.training.effective_batch}</b></span>
                    <span>معدل التعلم: <b className="num" dir="ltr">{gr.training.lr}</b></span>
                    <span>المدة: <b className="num" dir="ltr">{gr.training.seconds}s</b></span>
                  </div>
                </CardContent>
              </Card>
            </div>
          ) : (
            <Card><CardContent className="p-6 text-sm text-neutral-500">نتائج نموذج الذهب ستظهر هنا بعد اكتمال التدريب.</CardContent></Card>
          )}
        </motion.section>

        {/* بطاقات البيئة — ضمن مساحة النموذج */}
        <motion.section {...reveal} aria-label="البيئة" className="grid gap-3 sm:grid-cols-3">
          <Card>
            <CardContent className="p-4 text-sm text-neutral-400">
              <p className="mb-1 flex items-center gap-2 font-semibold text-neutral-200"><GitBranch className="h-4 w-4 text-amber-400" /> المستودع</p>
              <p className="break-all text-xs">AI4Finance-Foundation/FinGPT</p>
              <p className="num mt-1 break-all text-[11px] text-neutral-600" dir="ltr">{data?.repo?.commit || '—'}</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4 text-sm text-neutral-400">
              <p className="mb-1 flex items-center gap-2 font-semibold text-neutral-200"><Server className="h-4 w-4 text-amber-400" /> بيئة التشغيل</p>
              <p className="text-xs">{data?.sys?.cpus ?? '—'} أنوية · {data?.sys?.ram_gb ?? '—'} GB · CPU فقط</p>
              <p className="num mt-1 text-[11px] text-neutral-600" dir="ltr">torch {data?.verified?.torch || '—'} · transformers {data?.verified?.transformers || '—'}</p>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4 text-sm text-neutral-400">
              <p className="mb-1 flex items-center gap-2 font-semibold text-neutral-200"><FlaskConical className="h-4 w-4 text-amber-400" /> اختبارات المستودع</p>
              <p className="text-xs">{data?.verified?.pytest || '…'}</p>
              <p className="text-xs">Forex: {data?.verified?.forex || '…'}</p>
            </CardContent>
          </Card>
        </motion.section>
        </div>
        )}

        {/* ===== مساحة التدريب: مسارا التشغيل + نتائج المرحلة الأولى ===== */}
        {tab === 'training' && (
        <div className="space-y-8">

        {/* General pipeline */}
        <motion.section {...reveal} id="pipeline" aria-label="مسار التشغيل" className="scroll-mt-20">
          <h2 className="mb-3 flex items-center gap-2 text-lg font-bold"><Database className="h-5 w-5 text-amber-400" /> مسار التشغيل الحيّ — ضبط LoRA على المشاعر المالية</h2>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardContent className="p-4 sm:p-6">
                {!p && <p className="text-sm text-neutral-500">في انتظار أول قراءة…</p>}
                {p && (
                  <ol className="space-y-4">
                    {STEPS.map((s, i) => {
                      const state: 'running' | 'done' | 'pending' | 'error' =
                        errored && i === stageIdx ? 'error'
                          : errored && i < stageIdx ? 'done'
                          : i < stageIdx || p.stage === 'done' ? 'done'
                          : i === stageIdx ? (p.status === 'done' ? 'done' : 'running')
                          : 'pending'
                      return (
                        <li key={s.key} className="flex items-start gap-3">
                          <StageIcon state={state} />
                          <div className="min-w-0 flex-1">
                            <p className={`text-sm font-medium ${state === 'pending' ? 'text-neutral-600' : ''}`}>{s.label}</p>
                            {s.key === 'download_data' && p.train_n != null && (
                              <p className="num text-xs text-neutral-500" dir="ltr">{p.train_n} train · {p.test_n} test (HuggingFace: FinGPT)</p>
                            )}
                            {s.key === 'load_model' && p.trainable_params != null && (
                              <p className="text-xs text-neutral-500">Qwen2.5-0.5B-Instruct · قابل للتدريب: {fmtParams(p.trainable_params)} / {fmtParams(p.total_params)}</p>
                            )}
                            {s.key === 'baseline_eval' && p.acc_baseline != null && (
                              <p className="text-xs text-neutral-500">قبل الضبط: <b className="num" dir="ltr">{pct(p.acc_baseline)}</b></p>
                            )}
                            {s.key === 'training' && state === 'running' && p.step != null && (
                              <p className="num text-xs text-neutral-500" dir="ltr">step {p.step} · loss {p.loss ?? '—'} · {p.elapsed_s ?? 0}s</p>
                            )}
                            {s.key === 'export_adapter' && state === 'done' && p.adapter_mb != null && (
                              <p className="text-xs text-neutral-500">أوزان {p.adapter_mb} MB في <span dir="ltr" className="font-mono">fingpt_run/adapter</span></p>
                            )}
                            {s.key === 'finetuned_eval' && p.acc_final != null && (
                              <p className="text-xs text-neutral-500">بعد الضبط: <b className="num text-emerald-400" dir="ltr">{pct(p.acc_final)}</b></p>
                            )}
                            {errored && s.key === p.stage && (
                              <p className="mt-1 break-all rounded bg-red-950/60 p-2 font-mono text-xs text-red-400">{p.detail}</p>
                            )}
                          </div>
                        </li>
                      )
                    })}
                  </ol>
                )}
              </CardContent>
            </Card>

            {/* Gold pipeline */}
            <Card>
              <CardContent className="p-4 sm:p-6">
                <p className="mb-3 flex items-center gap-2 text-sm font-bold text-amber-300"><Coins className="h-4 w-4" /> مسار تخصص الذهب (مضاف عليه)</p>
                {!gp && <p className="text-sm text-neutral-500">لم يبدأ بعد.</p>}
                {gp && (
                  <ol className="space-y-4">
                    {GOLD_STEPS.map((s, i) => {
                      const state: 'running' | 'done' | 'pending' | 'error' =
                        gErrored && i === gStageIdx ? 'error'
                          : gErrored && i < gStageIdx ? 'done'
                          : i < gStageIdx || gp.stage === 'done' ? 'done'
                          : i === gStageIdx ? (gp.status === 'done' ? 'done' : 'running')
                          : 'pending'
                      return (
                        <li key={s.key} className="flex items-start gap-3">
                          <StageIcon state={state} />
                          <div className="min-w-0 flex-1">
                            <p className={`text-sm font-medium ${state === 'pending' ? 'text-neutral-600' : ''}`}>{s.label}</p>
                            {s.key === 'filter_data' && gp.train_n != null && (
                              <p className="num text-xs text-neutral-500" dir="ltr">{gp.train_n} train · {gp.test_n} test (gold-only)</p>
                            )}
                            {s.key === 'gold_training' && state === 'running' && gp.step != null && (
                              <p className="num text-xs text-neutral-500" dir="ltr">step {gp.step} · loss {gp.loss ?? '—'} · {gp.elapsed_s ?? 0}s</p>
                            )}
                            {s.key === 'save_adapter' && state === 'done' && gp.adapter_mb != null && (
                              <p className="text-xs text-neutral-500">محوّل {gp.adapter_mb} MB في <span dir="ltr" className="font-mono">fingpt_run/adapter_gold</span></p>
                            )}
                            {s.key === 'eval_gold' && state === 'done' && (
                              <p className="num text-xs text-neutral-500" dir="ltr">gold {pct(gp.acc_gold)} · general {pct(gp.acc_general)} · base {pct(gp.acc_base)}</p>
                            )}
                            {gErrored && s.key === gp.stage && (
                              <p className="mt-1 break-all rounded bg-red-950/60 p-2 font-mono text-xs text-red-400">{gp.detail}</p>
                            )}
                          </div>
                        </li>
                      )
                    })}
                  </ol>
                )}
              </CardContent>
            </Card>
          </div>
        </motion.section>

        {/* General results */}
        {res && (
          <motion.section {...reveal} aria-label="نتائج النموذج العام">
            <h2 className="mb-3 text-lg font-bold">نتائج النموذج العام (المرحلة الأولى)</h2>
            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-base">دقة تصنيف المشاعر ({res.eval.n} مثالاً)</CardTitle></CardHeader>
                <CardContent className="space-y-4">
                  <Bar label="قبل الضبط (نموذج أساسي)" value={res.eval.acc_before} color="bg-neutral-500" />
                  <Bar label="بعد ضبط LoRA ببيانات FinGPT" value={res.eval.acc_after} color="bg-emerald-500" />
                  <p className="text-xs text-neutral-500">قالب FinGPT الرسمي: <span dir="ltr" className="font-mono">Instruction / Input / Answer</span></p>
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-base">تفاصيل الضبط</CardTitle></CardHeader>
                <CardContent className="space-y-3 text-sm text-neutral-400">
                  <LossCurve curve={res.training.loss_curve} color="#34d399" />
                  <div className="num grid grid-cols-2 gap-x-4 gap-y-1 text-xs" dir="ltr">
                    <span>steps: <b>{res.training.steps}</b></span>
                    <span>batch: <b>{res.training.effective_batch}</b></span>
                    <span>lr: <b>{res.training.lr}</b></span>
                    <span>secs: <b>{res.training.seconds}</b></span>
                    <span>LoRA: <b>r={res.lora.r}, α={res.lora.alpha}</b></span>
                    <span>targets: <b>{res.lora.targets.join('/')}</b></span>
                  </div>
                </CardContent>
              </Card>
            </div>
          </motion.section>
        )}
        </div>
        )}

        {/* ===== مساحة وضع Dock — نوافذ قابلة للرسو والتعويم والتحجيم ===== */}
        {tab === 'dock' && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="flex flex-wrap items-center gap-2 text-lg font-bold">
                <LayoutGrid className="h-5 w-5 text-amber-400" />
                وضع <span className="gold-text">Dock</span> — نوافذ قابلة للرسو والتعويم
                <span className="text-xs font-normal text-neutral-500">rc-dock · اسحب أي تبويب وأفلته على أي حافة</span>
              </h2>
              <button
                onClick={() => { try { localStorage.removeItem('fingpt-dock-layout') } catch { /* تجاهل */ }; setDockKey((k) => k + 1) }}
                className="rounded-lg border border-neutral-700 px-3 py-1.5 text-xs text-neutral-400 transition hover:border-amber-500/40 hover:text-amber-300"
              >
                إعادة ضبط التخطيط
              </button>
            </div>
            <div className="h-[calc(100vh-235px)] min-h-[600px]">
              <DockWorkspace
                key={dockKey}
                candles={goldDaily?.candles ?? []}
                sentiment={sent}
                newsRows={newsRows}
                onRowDone={onNewsRowDone}
                onReset={onNewsReset}
                trend={trend}
              />
            </div>
          </div>
        )}
      </main>

      <footer className="relative z-10 mt-auto border-t border-amber-500/10 bg-neutral-950/60 py-3 text-center text-xs text-neutral-500">
        FinGPT Gold Terminal — بيانات COMEX حقيقية من Yahoo Finance · تصنيف لحظي على CPU · آخر تحديث:{' '}
        <span dir="ltr" className="num">{data ? new Date(data.ts).toLocaleTimeString('en-GB') : '—'}</span>
      </footer>

      <CommandPalette actions={actions} />
    </div>
  )
}
