(() => { document.getElementById('gold-inject')?.remove(); const s = document.createElement('style'); s.id='gold-inject'; s.textContent = `/* ============================================================
   🥇 ثيم الذهب — نسخة لوحة الإدارة (Yemen Smart · Gold Edition)
   ملف Override جاهز: أضفه في نهاية src/app/globals.css
   أو احقنه كوسم <style> للتجربة الفورية.
   يقلّب اللوحة الفاتحة (سماوي/كحلي/رمادي) إلى هوية الذهب الداكنة.
   ============================================================ */

/* ---------- 1) متغيرات shadcn → هوية الذهب (تعمل حتى في الوضع الفاتح) ---------- */
:root, .light, .dark {
  --background: oklch(0.16 0.01 85);
  --foreground: oklch(0.93 0.012 85);
  --card: oklch(0.2 0.012 85);
  --card-foreground: oklch(0.93 0.012 85);
  --popover: oklch(0.19 0.012 85);
  --popover-foreground: oklch(0.93 0.012 85);
  --primary: oklch(0.78 0.145 82);
  --primary-foreground: oklch(0.18 0.03 82);
  --secondary: oklch(0.26 0.015 85);
  --secondary-foreground: oklch(0.93 0.012 85);
  --muted: oklch(0.25 0.012 85);
  --muted-foreground: oklch(0.66 0.02 85);
  --accent: oklch(0.28 0.025 82);
  --accent-foreground: oklch(0.95 0.03 85);
  --destructive: oklch(0.704 0.191 22.216);
  --border: oklch(1 0 0 / 9%);
  --input: oklch(1 0 0 / 13%);
  --ring: oklch(0.78 0.145 82 / 55%);
  --radius: 0.625rem;
  --sidebar: oklch(0.19 0.012 85);
  --sidebar-foreground: oklch(0.93 0.012 85);
  --sidebar-primary: oklch(0.78 0.145 82);
  --sidebar-primary-foreground: oklch(0.18 0.03 82);
  --sidebar-accent: oklch(0.28 0.025 82);
  --sidebar-accent-foreground: oklch(0.95 0.03 85);
  --sidebar-border: oklch(1 0 0 / 8%);
  --sidebar-ring: oklch(0.78 0.145 82 / 55%);
  color-scheme: dark;
}

/* ---------- 2) الأساس: خلفية سوداء دافئة + نص أبيض دافئ ---------- */
html, body {
  background: #0f0d08 !important;
  color: #ebe7df !important;
}
/* الهالة الذهبية العلوية — بصمة الثيم */
body::before {
  content: "";
  position: fixed;
  inset-inline: 0;
  top: 0;
  height: 320px;
  z-index: 0;
  pointer-events: none;
  background: radial-gradient(ellipse at top, rgba(245, 158, 11, 0.12), transparent 62%);
}

/* ---------- 3) الخلفيات الفاتحة → درجات الذهب الداكنة ---------- */
.bg-white, .bg-sky-50, .bg-sky-100, .bg-sky-200,
.bg-slate-50, .bg-slate-100, .bg-slate-200,
.bg-gray-50, .bg-gray-100, .bg-gray-200,
.bg-stone-50, .bg-stone-100, .bg-stone-200,
.bg-blue-50, .bg-blue-100, .bg-zinc-50, .bg-zinc-100 {
  background-color: #12100a !important;
}
/* الأسطح الكحلية الداكنة (رؤوس الجداول، أزرار داكنة) → بطاقات ذهبية */
.bg-slate-700, .bg-slate-800, .bg-slate-900, .bg-slate-950,
.bg-gray-800, .bg-gray-900, .bg-zinc-800, .bg-zinc-900, .bg-stone-800 {
  background-color: #24211b !important;
}

/* ---------- 4) النصوص ---------- */
.text-slate-900, .text-slate-800, .text-slate-700,
.text-gray-900, .text-gray-800, .text-gray-700,
.text-stone-800, .text-stone-900, .text-zinc-900, .text-zinc-800,
.text-sky-900, .text-sky-800, .text-blue-900, .text-blue-800 {
  color: #ebe7df !important;
}
.text-slate-600, .text-slate-500, .text-gray-600, .text-gray-500,
.text-stone-600, .text-stone-500, .text-zinc-600, .text-zinc-500 {
  color: #a8a29e !important;
}
.text-slate-400, .text-slate-300, .text-gray-400, .text-gray-300 {
  color: #78716c !important;
}
/* الروابط والعناصر النشطة السماوية/الزرقاء → ذهبي */
.text-sky-600, .text-sky-700, .text-blue-600, .text-blue-700,
.text-sky-500, .text-blue-500, .text-cyan-600, .text-teal-600 {
  color: #fcd34d !important;
}

/* ---------- 5) الحدود ---------- */
.border-slate-200, .border-slate-300, .border-gray-200, .border-gray-300,
.border-stone-200, .border-zinc-200, .border-slate-800, .border-slate-700,
.border-gray-800, .border-sky-200, .border-blue-200 {
  border-color: rgba(245, 158, 11, 0.18) !important;
}

/* ---------- 6) الشريط الإخباري العلوي (Ticker) ---------- */
.fixed.inset-x-0.top-0 {
  background: rgba(12, 10, 6, 0.96) !important;
  border-bottom: 1px solid rgba(245, 158, 11, 0.15) !important;
  backdrop-filter: blur(10px);
}
.fixed.inset-x-0.top-0 .text-emerald-300 { color: #fde68a !important; }
.fixed.inset-x-0.top-0 .bg-emerald-400 { background: #fbbf24 !important; }
.fixed.inset-x-0.top-0 .text-slate-500 { color: #989285 !important; }

/* ---------- 7) شريط التنقل الأفقي ---------- */
nav a, nav button { transition: color 0.15s, background 0.15s; border-radius: 8px; }
nav a:hover, nav button:hover { color: #fde68a !important; background: rgba(245, 158, 11, 0.08) !important; }
/* التبويب النشط: خط سفلي ذهبي متوهج بدل الأخضر/الأزرق */
nav a[data-active="true"], nav a[aria-current="page"],
nav .border-emerald-500, nav [class*="border-emerald"],
nav .border-sky-500, nav .border-blue-500 {
  color: #fbbf24 !important;
  border-color: #f59e0b !important;
  text-shadow: 0 0 14px rgba(245, 158, 11, 0.35);
}

/* ---------- 8) الشريط الجانبي (shadcn Sidebar) ---------- */
[data-sidebar="sidebar"], [data-sidebar="sidebar"] * {
  border-color: rgba(245, 158, 11, 0.12);
}
[data-sidebar="menu-button"] { color: #a8a29e !important; }
[data-sidebar="menu-button"]:hover,
[data-sidebar="menu-button"][data-active="true"] {
  background: rgba(245, 158, 11, 0.12) !important;
  color: #fbbf24 !important;
}
[data-sidebar="menu-sub-button"] { color: #989285 !important; }
[data-sidebar="menu-sub-button"]:hover,
[data-sidebar="menu-sub-button"][data-active="true"] {
  color: #fcd34d !important;
  background: rgba(245, 158, 11, 0.08) !important;
}
[data-sidebar="group-label"] { color: #78716c !important; letter-spacing: 0.02em; }

/* ---------- 9) الجداول ---------- */
table { color: #ebe7df; }
thead, thead tr {
  background: linear-gradient(to left, rgba(245, 158, 11, 0.14), rgba(245, 158, 11, 0.05)) !important;
}
thead th { color: #fde68a !important; font-weight: 600; border-bottom: 1px solid rgba(245, 158, 11, 0.25) !important; }
tbody tr { border-bottom: 1px solid rgba(255, 255, 255, 0.06) !important; }
tbody tr:hover { background: rgba(245, 158, 11, 0.05) !important; }
tbody tr[data-state="selected"] { background: rgba(245, 158, 11, 0.09) !important; }
/* أرقام وأكواد الحسابات بمحاذاة tabular */
td .font-mono, td code, td[class*="tabular"] { font-variant-numeric: tabular-nums; letter-spacing: -0.01em; }

/* ---------- 10) الشارات: النجاح يبقى أخضر، والباقي بهوية الذهب ---------- */
.bg-emerald-100, [class*="bg-emerald"][class*="text-emerald"] {
  background-color: rgba(5, 150, 105, 0.18) !important;
}
.bg-sky-100, .bg-blue-100, .bg-sky-500\\/15 {
  background-color: rgba(245, 158, 11, 0.15) !important;
  color: #fcd34d !important;
}

/* ---------- 11) الأزرار والحقول ---------- */
button, [role="button"], select, input {
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
select, input {
  background: rgba(255, 255, 255, 0.04) !important;
  border-color: rgba(255, 255, 255, 0.13) !important;
  color: #ebe7df !important;
}
select:focus, input:focus {
  border-color: rgba(245, 158, 11, 0.55) !important;
  box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.18) !important;
  outline: none !important;
}
.bg-primary, .bg-primary\\/90 { background-color: #e5ad34 !important; color: #181003 !important; }

/* ---------- 12) شريط تمرير رفيع ---------- */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-thumb { background: #44403c; border-radius: 8px; }
::-webkit-scrollbar-track { background: transparent; }

/* ---------- 13) الأرقام: أضف IBM Plex Mono في المشروع الأصلي ----------
   @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&display=swap');
   .font-mono { font-family: 'IBM Plex Mono', monospace !important; }
-------------------------------------------------------------- */

/* ============================================================
   14) طبقة الالتقاط الشامل — لأصناف Tailwind بمعدّل الشفافية
   مثل bg-sky-50/80 و bg-white/60 و bg-sidebar التي لا تلتقطها
   المحددات البسيطة. (مهم جداً — لا تحذفها)
   ============================================================ */
[class*="bg-sidebar"] { background-color: #16130e !important; }
[class*="bg-white"] { background-color: rgba(245, 158, 11, 0.07) !important; }
[class*="bg-sky-"], [class*="bg-blue-"] { background-color: #12100a !important; }
[class*="bg-slate-5"], [class*="bg-slate-1"], [class*="bg-slate-2"],
[class*="bg-gray-5"], [class*="bg-gray-1"], [class*="bg-gray-2"],
[class*="bg-zinc-5"], [class*="bg-zinc-1"], [class*="bg-zinc-2"],
[class*="bg-stone-5"], [class*="bg-stone-1"], [class*="bg-stone-2"] {
  background-color: #12100a !important;
}
[class*="bg-slate-8"], [class*="bg-slate-9"], [class*="bg-gray-8"], [class*="bg-gray-9"] {
  background-color: #24211b !important;
}
/* نصوص الشريط الجانبي والهيدر الفاتحة فوق الداكن */
[class*="text-sky-9"], [class*="text-slate-9"], [class*="text-slate-8"], [class*="text-gray-9"] {
  color: #ebe7df !important;
}
[class*="border-sky-"], [class*="border-blue-"] {
  border-color: rgba(245, 158, 11, 0.18) !important;
}
/* عنصر الشريط الجانبي الثابت */
.fixed[class*="inset-y-0"] { background: #12100a !important; }
`; document.head.appendChild(s); return 'gold v2 injected: ' + s.textContent.length + ' chars'; })()