#!/bin/bash
# ============================================================
# رفع النسخة الاحتياطية إلى GitHub — مجلد فرعي معزول
# backup-gold-2026-11-03/ داخل sssalaa05-lab/Yemen_Smart
# التوكِن يُستخدم عابراً فقط ولا يُطبع ولا يُخزَّن
# ============================================================
set -euo pipefail

TOK=/home/z/.ghp_tmp
REPO_DIR=/tmp/yspush
SUBFOLDER=backup-gold-2026-11-03
BK=/home/z/my-project/download/GITHUB_BACKUP_yemen-smart-2026-11-03

mask() { sed -E 's/x-access-token:[^@[:space:]]*@/***/g; s/gh[pousr]_[A-Za-z0-9_]+/***/g'; }

echo "==> 1) استنساخ المستودع (بدون توكن في الإعدادات)"
rm -rf "$REPO_DIR"
git clone --depth 1 "https://github.com/sssalaa05-lab/Yemen_Smart.git" "$REPO_DIR" 2>&1 | mask

cd "$REPO_DIR"

echo "==> 2) إنشاء المجلد الفرعي ونسخ النسخة الاحتياطية داخله"
mkdir -p "$SUBFOLDER"
rsync -a "$BK/" "$SUBFOLDER/"

echo "==> 3) إضافة الملفات (فرض التجاوز لأي .ignore موجود في المستودع)"
git add -f "$SUBFOLDER/"
COUNT=$(git diff --cached --numstat | wc -l)
echo "    ملفات جديدة: $COUNT"

echo "==> 4) الحفظ (commit)"
git -c user.name="Z Backup" -c user.email="z@container" \
  commit -m "🥇 Backup: FinGPT Gold dashboard + Yemen Smart gold panel — full session (2026-11-03)

- 01-project: Next.js 16 dashboard (candles, live news, signals, dock, command palette) + Yemen Smart gold panel (Jan-1970 fixed)
- 02-packages: design-theme-kit + yemen-smart-gold identity packs
- 03-model: FinGPT repo + trained LoRA adapters (general 75% / gold 92.5%)
- README.md: full session log · RESTORE.md: recovery steps" 2>&1 | mask

echo "==> 5) الدفع إلى main"
git push "https://x-access-token:$(cat "$TOK")@github.com/sssalaa05-lab/Yemen_Smart.git" main 2>&1 | mask

echo "==> 6) حذف التوكِن المؤقت نهائياً"
rm -f "$TOK" && echo "    ✓ تم الحذف"

echo "==> DONE"
