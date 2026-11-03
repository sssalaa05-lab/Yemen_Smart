#!/usr/bin/env python3
"""تصدير مجموعة تقييم الذهب (نصوص حقيقية من FinGPT) لقاعة الأخبار الحية في الداشبورد"""
import os, re, json

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ["HF_DATASETS_OFFLINE"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

OUT = "/home/z/my-project/fingpt_run/gold_test_set.json"
KW = re.compile(r"\bgold\b|xau|\bgld\b|bullion|precious metal|\bgdx\b", re.I)


def main():
    from datasets import load_dataset
    cls = load_dataset("FinGPT/fingpt-sentiment-cls", split="train")
    # نفس تقسيم fingpt_gold.py بالضبط (seed=42) حتى تبقى عناوين الاختبار غير مرئية أثناء التدريب
    split = cls.train_test_split(test_size=0.2, shuffle=True, seed=42)
    rows = [dict(r) for r in split["test"] if KW.search(r.get("input") or "")][:40]
    out = [{"id": i, "input": r["input"][:220], "output": r["output"]} for i, r in enumerate(rows)]
    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
    print("saved", len(out), "rows ->", OUT)
    for r in out[:3]:
        print("-", r["output"], "|", r["input"][:80])


if __name__ == "__main__":
    main()
