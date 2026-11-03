#!/bin/bash
# ============================================================
# بناء النسخة الاحتياطية المستقلة — كل أعمال الجلسة 2026-11-03
# النسخة تُبنى في download/ ولا تمس ملفات المشروع الأصلي إطلاقاً
# ============================================================
set -euo pipefail

SRC=/home/z/my-project
BK="$SRC/download/GITHUB_BACKUP_yemen-smart-2026-11-03"

rm -rf "$BK"
mkdir -p "$BK/01-project" "$BK/02-packages" "$BK/03-model"

echo "==> 1) نسخ المشروع الكامل (بدون node_modules و.build و.git)"
rsync -a \
  --exclude 'node_modules' \
  --exclude '.next' \
  --exclude 'download' \
  --exclude '.git' \
  --exclude '*.tsbuildinfo' \
  --exclude 'dev.log' \
  --exclude 'GITHUB_BACKUP_*' \
  --exclude 'FinGPT' \
  --exclude 'fingpt_run' \
  "$SRC/" "$BK/01-project/"

echo "==> 2) حزم التصميم والهوية"
rsync -a "$SRC/download/design-theme-kit"   "$BK/02-packages/" 2>/dev/null || echo "   (design-theme-kit غير موجود — تخطي)"
rsync -a "$SRC/download/yemen-smart-gold"   "$BK/02-packages/" 2>/dev/null || echo "   (yemen-smart-gold غير موجود — تخطي)"

echo "==> 3) النموذج والمحوّلات (FinGPT بدون .git + fingpt_run)"
rsync -a --exclude '.git' \
  --exclude 'FinGPT_MultiAgentsRAG/Fine_tune_model/fine_tune_Llama2.ipynb' \
  --exclude 'FinGPT_MultiAgentsRAG/Fine_tune_model/fine_tune_GLM2.ipynb' \
  "$SRC/FinGPT" "$BK/03-model/" 2>/dev/null || echo "   (FinGPT غير موجود — تخطي)"
rsync -a "$SRC/fingpt_run"                  "$BK/03-model/" 2>/dev/null || echo "   (fingpt_run غير موجود — تخطي)"

echo "==> الأحجام:"
du -sh "$BK/01-project" "$BK/02-packages" "$BK/03-model" 2>/dev/null
echo "==> الإجمالي:"
du -sh "$BK"
echo "==> عدد الملفات:"
find "$BK" -type f | wc -l
