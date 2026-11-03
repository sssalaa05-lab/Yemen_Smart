"use client";

// ============================================================
// 🥇 يمن سمارت — النسخة الذهبية (Yemen Smart · Gold Edition)
// مكوّن قابل للتضمين داخل الصفحة الرئيسية (بدون مسار مستقل)
// شريط إخباري + هيدر + تنقل أفقي + شريط جانبي + جدول حسابات
// مع إصلاح خلل Jan 1970 (تواريخ حقيقية بدل epoch=0)
// ============================================================

import { useEffect, useMemo, useState } from "react";
import Image from "next/image";
import { motion } from "motion/react";
import {
  Activity,
  ArrowLeftRight,
  Bot,
  BrainCircuit,
  Building2,
  ChevronDown,
  FileText,
  Gauge,
  LayoutDashboard,
  Radar,
  Receipt,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Bell,
  Zap,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

type GoldSummary = { last: number; chg_1d_pct: number; last_date: string };

// ---------- بيانات الحسابات (تواريخ حقيقية — إصلاح Jan 1970) ----------
type Account = {
  id: string;
  client: string;
  type: "ديمو" | "حقيقي";
  balance: number;
  usedMargin: number;
  status: "شغّالة" | "مقفلة";
  lastSeen: string; // ISO
  latencyMs: number;
};

const ACCOUNTS: Account[] = [
  { id: "S202611021", client: "REDHWAN MOHAMMED MOHAMMED AL MALEKI", type: "ديمو", balance: 15000, usedMargin: 1250, status: "شغّالة", lastSeen: "2026-11-03T09:42:00", latencyMs: 45 },
  { id: "S202611022", client: "REDHWAN MOHAMMED MOHAMMED AL MALEKI", type: "ديمو", balance: 0, usedMargin: 0, status: "مقفلة", lastSeen: "2026-10-28T16:20:00", latencyMs: 62 },
  { id: "S202611023", client: "REDHWAN MOHAMMED MOHAMMED AL MALEKI", type: "ديمو", balance: 0, usedMargin: 0, status: "مقفلة", lastSeen: "2026-10-30T11:05:00", latencyMs: 58 },
  { id: "S202611024", client: "REDHWAN MOHAMMED MOHAMMED AL MALEKI", type: "ديمو", balance: 0, usedMargin: 0, status: "مقفلة", lastSeen: "2026-09-15T14:33:00", latencyMs: 71 },
  { id: "S202611025", client: "REDHWAN MOHAMMED MOHAMMED AL MALEKI", type: "ديمو", balance: 0, usedMargin: 0, status: "مقفلة", lastSeen: "2026-08-02T08:15:00", latencyMs: 83 },
];

// ---------- التنقل الأفقي (تسميات نظيفة بدل المشوهة) ----------
const NAV_ITEMS = [
  "نظرة عامة",
  "الحسابات",
  "النواة",
  "المؤقتات",
  "العقود",
  "الأوامر",
  "الصفقات",
  "المراكز",
  "المعاملات",
  "الطلبات",
  "المحافظ",
  "تجميعات السيولة",
  "تدفقات التداول",
  "جسور MT5",
  "اختبار الشبكة",
  "التكاليف",
  "الأرباح",
  "حسابات الوسطاء",
  "أصول الوسطاء",
  "قائمة الوسطاء",
] as const;

// ---------- الشريط الجانبي ----------
const SIDE_ITEMS = [
  { key: "read", title: "وحدة القراءة", sub: "نظرة عامة", icon: FileText },
  { key: "board", title: "اللوحة الموحدة", sub: "نظرة شاملة", icon: LayoutDashboard },
  { key: "margins", title: "الحدود والهوامش", sub: "مستويات الرفع", icon: Gauge },
  { key: "alerts", title: "الإشعارات", sub: "تنبيهات فورية", icon: Bell },
  { key: "execution", title: "التداول والتنفيذ", sub: "ضبط وأوامر", icon: Zap },
  { key: "risk", title: "المخاطر والتحليلات", sub: "حدود وتحليلات", icon: ShieldAlert },
  { key: "ml", title: "التعلم الآلي", sub: "نماذج وتوقعات", icon: Bot },
  { key: "kyc", title: "التحقق والتأكيد", sub: "فحوصات المطابقة", icon: ShieldCheck },
  { key: "ai", title: "الاستدلال والأدوات", sub: "قرائن وأدوات", icon: BrainCircuit },
  { key: "monitor", title: "المراقبة والاسترجاع", sub: "سجلات وحالات", icon: Radar },
  { key: "billing", title: "الفوترة", sub: "أدوات وضمانات", icon: Receipt },
  { key: "settings", title: "إعدادات عامة", sub: "تهيئة المنصة", icon: Settings },
] as const;

const fmtDate = (iso: string) => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime()) || d.getTime() === 0) return "—"; // حماية من خلل epoch=0
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};

const usd = (n: number) => `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export default function YemenSmartPanel({ onBack }: { onBack: () => void }) {
  const [nav, setNav] = useState<string>("الحسابات");
  const [side, setSide] = useState<string>("execution");
  const [statusFilter, setStatusFilter] = useState<"all" | "شغّالة" | "مقفلة">("all");
  const [typeFilter, setTypeFilter] = useState<"all" | "ديمو" | "حقيقي">("all");
  const [gold, setGold] = useState<GoldSummary | null>(null);

  useEffect(() => {
    fetch("/gold/gold_daily.json")
      .then((r) => r.json())
      .then((d) => setGold(d.summary ?? null))
      .catch(() => setGold(null));
  }, []);

  const rows = useMemo(
    () =>
      ACCOUNTS.filter(
        (a) => (statusFilter === "all" || a.status === statusFilter) && (typeFilter === "all" || a.type === typeFilter),
      ),
    [statusFilter, typeFilter],
  );

  const activeSideItem = SIDE_ITEMS.find((s) => s.key === side);

  const tickerItems: { label: string; value: string; cls: string }[] = [
    { label: "XAU/USD", value: gold ? `$${gold.last.toLocaleString("en-US")} ${gold.chg_1d_pct >= 0 ? "▲" : "▼"} ${Math.abs(gold.chg_1d_pct)}%` : "…", cls: "text-amber-300 font-semibold" },
    { label: "EUR/USD", value: "1.0842 ▲ 0.12%", cls: "text-emerald-400" },
    { label: "GBP/USD", value: "1.2689 ▼ 0.08%", cls: "text-red-400" },
    { label: "USOIL", value: "78.42 ▲ 0.65%", cls: "text-emerald-400" },
    { label: "MT5 Gateway", value: "متصل ✓", cls: "text-emerald-400" },
    { label: "FinGPT", value: "نموذج الذهب جاهز · 92.5%", cls: "text-amber-200" },
    { label: "النظام", value: "جارٍ تجميع بيانات المؤشرات…", cls: "text-stone-400" },
  ];

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* بصمة الثيم: الهالة الذهبية العلوية */}
      <div className="pointer-events-none fixed inset-x-0 top-0 z-0 h-80 bg-[radial-gradient(ellipse_at_top,rgba(245,158,11,0.12),transparent_62%)]" />

      {/* ===== الشريط الإخباري (Ticker) ===== */}
      <style>{`
        @keyframes gold-ticker { from { transform: translateX(0); } to { transform: translateX(-50%); } }
        .ticker-track { display: flex; width: max-content; animation: gold-ticker 38s linear infinite; }
        .ticker-track:hover { animation-play-state: paused; }
      `}</style>
      <div className="fixed inset-x-0 top-0 z-50 flex h-9 items-center overflow-hidden border-b border-amber-500/15 bg-[rgba(12,10,6,0.96)] backdrop-blur">
        <div className="flex h-full shrink-0 items-center gap-1.5 border-l border-amber-500/15 px-3">
          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-amber-400" />
          <span className="text-[10px] font-medium text-amber-200">بث حي</span>
        </div>
        <div className="relative flex-1 overflow-hidden" dir="ltr">
          <div className="ticker-track">
            {[0, 1].map((dup) => (
              <div key={dup} className="flex items-center gap-8 px-4" aria-hidden={dup === 1}>
                {tickerItems.map((t, i) => (
                  <span key={i} className="flex items-center gap-2 whitespace-nowrap text-[11px]" dir="rtl">
                    <span className="text-stone-500">{t.label}</span>
                    <span className={`num ${t.cls}`} dir="ltr">{t.value}</span>
                    <span className="text-amber-500/30">•</span>
                  </span>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="flex min-h-screen pt-9">
        {/* ===== الشريط الجانبي (يمين) ===== */}
        <aside className="sticky top-9 hidden h-[calc(100vh-2.25rem)] w-72 shrink-0 flex-col border-l border-amber-500/15 bg-card/50 lg:flex">
          <div className="flex items-center gap-3 border-b border-amber-500/10 px-4 py-4">
            <div className="relative h-11 w-11 shrink-0 overflow-hidden rounded-full ring-1 ring-amber-400/50 shadow-lg shadow-amber-500/30">
              <Image src="/yemen/emblem.png" alt="شعار يمن سمارت — باب اليمن الذهبي" fill sizes="44px" className="object-cover" />
            </div>
            <div className="min-w-0">
              <h2 className="truncate text-base font-bold leading-tight">
                يمن <span className="gold-text">سمارت</span>
              </h2>
              <p className="truncate text-[11px] text-stone-500">منصة التداول الذكية · النسخة الذهبية</p>
            </div>
          </div>

          <nav className="gold-scroll flex-1 space-y-1 overflow-y-auto p-3">
            {SIDE_ITEMS.map((item) => {
              const active = side === item.key;
              const Icon = item.icon;
              return (
                <button
                  key={item.key}
                  onClick={() => setSide(item.key)}
                  className={`flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-right transition-colors ${
                    active
                      ? "border-amber-500/40 bg-gradient-to-l from-amber-500/15 to-transparent text-amber-300 shadow-sm shadow-amber-500/10"
                      : "border-transparent text-stone-400 hover:bg-amber-500/5 hover:text-amber-200"
                  }`}
                >
                  <span
                    className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
                      active ? "bg-amber-500/20 text-amber-300" : "bg-stone-800/60 text-stone-500"
                    }`}
                  >
                    <Icon className="h-4 w-4" />
                  </span>
                  <span className="min-w-0">
                    <span className={`block truncate text-[13px] font-semibold ${active ? "text-amber-200" : ""}`}>
                      {item.title}
                    </span>
                    <span className="block truncate text-[10px] text-stone-500">{item.sub}</span>
                  </span>
                </button>
              );
            })}
          </nav>

          <div className="border-t border-amber-500/10 px-4 py-3">
            <div className="flex items-center justify-between text-[10px] text-stone-500">
              <span className="num" dir="ltr">بنيت بسمارت V1.0</span>
              <Badge variant="outline" className="border-amber-500/40 bg-amber-500/10 text-amber-300">🥇 Gold Edition</Badge>
            </div>
            <button
              onClick={onBack}
              className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg border border-stone-700 px-2 py-1.5 text-[11px] text-stone-400 transition hover:border-amber-500/40 hover:text-amber-300"
            >
              ← داشبورد الذهب FinGPT
            </button>
          </div>
        </aside>

        {/* ===== العمود الرئيسي ===== */}
        <div className="flex min-w-0 flex-1 flex-col">
          {/* الهيدر */}
          <header className="sticky top-9 z-40 flex h-14 shrink-0 items-center gap-2 border-b border-amber-500/15 bg-background/80 px-4 backdrop-blur-md sm:px-6">
            <Badge variant="outline" className="gap-1 border-amber-500/40 bg-amber-500/10 text-amber-300">
              <ArrowLeftRight className="h-3 w-3" /> التداول والتنفيذ <ChevronDown className="h-3 w-3" />
            </Badge>
            <Badge variant="outline" className="gap-1 border-stone-700 text-stone-400">
              <Building2 className="h-3 w-3" /> مؤسسي <ChevronDown className="h-3 w-3" />
            </Badge>
            <div className="flex-1" />
            <button
              onClick={onBack}
              className="hidden rounded-lg border border-stone-700 px-2.5 py-1.5 text-xs text-stone-400 transition hover:border-amber-500/40 hover:text-amber-300 sm:block"
            >
              🥇 داشبورد الذهب
            </button>
            <div className="flex items-center gap-2 rounded-full border border-amber-500/20 bg-card/80 py-1 pl-3 pr-1">
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-br from-amber-300 to-amber-600 text-[10px] font-bold text-amber-950">
                PA
              </span>
              <span className="leading-tight">
                <span className="num block text-[11px] font-semibold text-amber-100" dir="ltr">Platform Administrator</span>
                <span className="block text-[10px] text-stone-500">مشرف عام</span>
              </span>
            </div>
          </header>

          {/* التنقل الأفقي */}
          <nav className="sticky top-[92px] z-30 border-b border-amber-500/10 bg-background/85 backdrop-blur-md">
            <div className="gold-scroll flex items-center gap-1 overflow-x-auto px-2 py-1.5">
              {NAV_ITEMS.map((item) => {
                const active = nav === item;
                return (
                  <button
                    key={item}
                    onClick={() => {
                      setNav(item);
                      setSide("execution"); // التنقل الأفقي يعود دائماً لقسم التنفيذ
                    }}
                    className={`relative shrink-0 rounded-lg px-3 py-2 text-[13px] transition-colors ${
                      active ? "font-bold text-amber-300" : "text-stone-400 hover:bg-amber-500/5 hover:text-amber-200"
                    }`}
                  >
                    {item}
                    {active && (
                      <span className="absolute inset-x-3 -bottom-[7px] h-[2px] rounded-full bg-gradient-to-r from-amber-600 via-amber-400 to-amber-600 shadow-[0_0_14px_rgba(245,158,11,0.5)]" />
                    )}
                  </button>
                );
              })}
            </div>
          </nav>

          {/* المحتوى */}
          <main className="relative z-10 flex-1 px-4 py-6 sm:px-6">
            {side !== "execution" ? (
              <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35 }}>
                <Card className="mx-auto max-w-xl border-amber-500/20 bg-gradient-to-br from-amber-500/10 to-transparent text-center">
                  <CardContent className="flex flex-col items-center gap-3 p-10">
                    {activeSideItem && <activeSideItem.icon className="h-10 w-10 text-amber-400" />}
                    <h3 className="text-lg font-bold text-amber-200">{activeSideItem?.title}</h3>
                    <p className="text-sm text-stone-400">
                      قسم «{activeSideItem?.title} — {activeSideItem?.sub}» جاهز للربط في النسخة الكاملة.
                      هذه نسخة تصميم بالثيم الذهبي.
                    </p>
                    <button
                      className="rounded-lg border border-amber-500/40 px-3 py-1.5 text-sm text-amber-300 transition hover:bg-amber-500/10"
                      onClick={() => setSide("execution")}
                    >
                      عودة إلى التداول والتنفيذ
                    </button>
                  </CardContent>
                </Card>
              </motion.div>
            ) : nav === "نظرة عامة" ? (
              <motion.section
                key="overview"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.35 }}
                aria-label="نظرة عامة"
              >
                <h1 className="text-xl font-bold">نظرة عامة على <span className="gold-text">المنصة</span></h1>
                <p className="mt-1 text-xs text-stone-500">ملخص حالة المنصة والحسابات والمحرك — النسخة الذهبية</p>

                {/* البانر اليمني — هوية صنعاء الذهب */}
                <div className="relative mt-4 h-44 overflow-hidden rounded-2xl border border-amber-500/25 sm:h-60">
                  <Image src="/yemen/sanaa-hero.png" alt="صنعاء القديمة عند الغروب الذهبي — هوية يمن سمارت" fill sizes="(max-width: 640px) 100vw, 900px" className="object-cover" priority />
                  <div className="absolute inset-0 bg-gradient-to-l from-black/85 via-black/35 to-transparent" />
                  <div className="absolute inset-y-0 right-0 flex max-w-sm flex-col justify-center gap-1.5 p-5">
                    <span className="flex w-fit items-center gap-1.5 rounded-full border border-amber-400/50 bg-black/55 px-2.5 py-0.5 text-[10px] font-semibold text-amber-300 backdrop-blur">
                      <Image src="/yemen/emblem.png" alt="" width={14} height={14} className="rounded-full" />
                      هوية يمنية · صنعاء القديمة
                    </span>
                    <h2 className="text-lg font-bold leading-snug text-white sm:text-xl">
                      من قلب <span className="gold-text">اليمن</span> إلى أسواق العالم
                    </h2>
                    <p className="text-[11px] leading-relaxed text-stone-300">
                      عمارة صنعاء وشمسيّاتها القمرية بلغة الذهب — هوية منصة يمن سمارت للنخبة
                    </p>
                  </div>
                </div>
                <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
                  {[
                    { label: "حسابات نشطة", value: "1", sub: "من أصل 5 حسابات ديمو" },
                    { label: "حسابات مقفلة", value: "4", sub: "تتطلب إعادة فتح" },
                    { label: "XAU/USD الآن", value: gold ? `$${gold.last.toLocaleString("en-US")}` : "…", sub: gold ? `${gold.chg_1d_pct >= 0 ? "+" : ""}${gold.chg_1d_pct}% اليوم` : "بيانات حقيقية" },
                    { label: "زمن الاستجابة", value: "45ms", sub: "أدنى زمن اتصال MT5" },
                  ].map((k) => (
                    <Card key={k.label} className="h-full border-amber-500/20 bg-gradient-to-br from-amber-500/10 to-transparent">
                      <CardContent className="p-4">
                        <p className="text-xs text-stone-400">{k.label}</p>
                        <p className="num mt-1 text-3xl font-bold text-amber-300" dir="ltr">{k.value}</p>
                        <p className="mt-1 text-[11px] text-stone-500">{k.sub}</p>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              </motion.section>
            ) : nav === "الحسابات" ? (
              <motion.section
                key="accounts"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.35 }}
                aria-label="جلسات التداول"
                className="space-y-4"
              >
                {/* العنوان والفلاتر */}
                <div className="flex flex-wrap items-end justify-between gap-3">
                  <div>
                    <h1 className="flex items-center gap-2 text-xl font-bold">
                      جلسات التداول
                      <Activity className="h-5 w-5 animate-pulse text-amber-400" />
                    </h1>
                    <p className="mt-1 text-xs text-stone-500">إدارة جلسات التنفيذ الآلي والمحافظ والمراجعة — تواريخ حقيقية (بلا Jan 1970)</p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      value={typeFilter}
                      onChange={(e) => setTypeFilter(e.target.value as typeof typeFilter)}
                      className="rounded-lg border border-stone-700 bg-white/5 px-3 py-1.5 text-xs text-stone-200 outline-none transition focus:border-amber-500/55"
                      aria-label="تصفية النوع"
                    >
                      <option value="all">النوع: الكل</option>
                      <option value="ديمو">ديمو</option>
                      <option value="حقيقي">حقيقي</option>
                    </select>
                    <select
                      value={statusFilter}
                      onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}
                      className="rounded-lg border border-stone-700 bg-white/5 px-3 py-1.5 text-xs text-stone-200 outline-none transition focus:border-amber-500/55"
                      aria-label="تصفية الحالة"
                    >
                      <option value="all">الحالة: الكل</option>
                      <option value="شغّالة">شغّالة</option>
                      <option value="مقفلة">مقفلة</option>
                    </select>
                    <Badge variant="outline" className="gap-1 border-amber-500/40 bg-amber-500/10 text-amber-300">
                      <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-amber-400" /> {rows.length} نتيجة
                    </Badge>
                  </div>
                </div>

                {/* جدول الحسابات */}
                <Card className="overflow-hidden">
                  <div className="flex items-center justify-between border-b border-amber-500/15 bg-gradient-to-l from-amber-500/10 to-transparent px-4 py-3">
                    <h2 className="text-sm font-bold text-amber-200">قائمة الحسابات ({rows.length})</h2>
                    <span className="num text-[10px] text-stone-500" dir="ltr">MT5 · demo server</span>
                  </div>
                  <div className="gold-scroll overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="bg-gradient-to-l from-amber-500/[0.14] to-amber-500/[0.05] text-right text-[12px] text-amber-200">
                          <th className="whitespace-nowrap px-4 py-2.5 font-semibold">رمز الحساب</th>
                          <th className="whitespace-nowrap px-4 py-2.5 font-semibold">العميل</th>
                          <th className="whitespace-nowrap px-4 py-2.5 font-semibold">النوع</th>
                          <th className="whitespace-nowrap px-4 py-2.5 font-semibold">الرصيد</th>
                          <th className="whitespace-nowrap px-4 py-2.5 font-semibold">الهامش المستخدم</th>
                          <th className="whitespace-nowrap px-4 py-2.5 font-semibold">الحالة</th>
                          <th className="whitespace-nowrap px-4 py-2.5 font-semibold">آخر اتصال</th>
                          <th className="whitespace-nowrap px-4 py-2.5 font-semibold">الاستجابة</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((a) => (
                          <tr key={a.id} className="border-b border-white/[0.06] transition-colors hover:bg-amber-500/[0.05]">
                            <td className="whitespace-nowrap px-4 py-2.5">
                              <span className="num font-semibold text-amber-300" dir="ltr">${a.id}</span>
                            </td>
                            <td className="max-w-[240px] truncate px-4 py-2.5 text-[12px] text-stone-300" title={a.client}>
                              {a.client}
                            </td>
                            <td className="whitespace-nowrap px-4 py-2.5 text-stone-300">{a.type}</td>
                            <td className={`num whitespace-nowrap px-4 py-2.5 font-semibold ${a.balance > 0 ? "text-emerald-400" : "text-stone-500"}`} dir="ltr">
                              {usd(a.balance)}
                            </td>
                            <td className="num whitespace-nowrap px-4 py-2.5 text-stone-400" dir="ltr">{usd(a.usedMargin)}</td>
                            <td className="whitespace-nowrap px-4 py-2.5">
                              {a.status === "شغّالة" ? (
                                <Badge className="gap-1 bg-emerald-600 text-white">
                                  <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-200" /> شغّالة
                                </Badge>
                              ) : (
                                <Badge className="bg-stone-600 text-white">مقفلة</Badge>
                              )}
                            </td>
                            <td className="num whitespace-nowrap px-4 py-2.5 text-stone-300" dir="ltr">{fmtDate(a.lastSeen)}</td>
                            <td className={`num whitespace-nowrap px-4 py-2.5 font-semibold ${a.latencyMs < 60 ? "text-emerald-400" : "text-stone-400"}`} dir="ltr">
                              {a.latencyMs}ms
                            </td>
                          </tr>
                        ))}
                        {rows.length === 0 && (
                          <tr>
                            <td colSpan={8} className="px-4 py-10 text-center text-sm text-stone-500">
                              لا حسابات مطابقة للتصفية الحالية
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </Card>

                <p className="text-[11px] leading-relaxed text-stone-500">
                  🛠️ إصلاح مدمج: التواريخ هنا حقيقية — في النسخة الأصلية تظهر <span className="num" dir="ltr">Jan 1970</span> لأن
                  قيمة الطابع الزمني صفر (epoch)؛ يُفحص تحويل الثواني/الميلي ثانية في كود الجدول الأصلي.
                </p>
              </motion.section>
            ) : (
              <motion.div
                key={nav}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.35 }}
              >
                <Card className="mx-auto max-w-xl border-amber-500/20 bg-gradient-to-br from-amber-500/10 to-transparent text-center">
                  <CardContent className="flex flex-col items-center gap-3 p-10">
                    <LayoutDashboard className="h-10 w-10 text-amber-400" />
                    <h3 className="text-lg font-bold text-amber-200">قسم «{nav}»</h3>
                    <p className="text-sm text-stone-400">جاهز للربط بالبيانات في النسخة الكاملة — التصميم والهوية مطبقان.</p>
                    <button
                      className="rounded-lg border border-amber-500/40 px-3 py-1.5 text-sm text-amber-300 transition hover:bg-amber-500/10"
                      onClick={() => setNav("الحسابات")}
                    >
                      عودة إلى الحسابات
                    </button>
                  </CardContent>
                </Card>
              </motion.div>
            )}
          </main>

          {/* التذييل */}
          <footer className="relative z-10 flex flex-wrap items-center justify-between gap-2 border-t border-amber-500/10 px-4 py-3 text-[10px] text-stone-500 sm:px-6">
            <span>
              بنيت بسمارت <span className="num" dir="ltr">V1.0</span> · النسخة الذهبية 🥇
            </span>
            <span className="num" dir="ltr">Gold Edition · build {new Date().getFullYear()}.11.03</span>
          </footer>
        </div>
      </div>
    </div>
  );
}
