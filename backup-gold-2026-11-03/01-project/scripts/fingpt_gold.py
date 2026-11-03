#!/usr/bin/env python3
"""FinGPT gold specialization: CONTINUE-train the general LoRA adapter on
gold-market rows only (domain-adaptive specialization, FinGPT-style), then
compare base vs general vs gold on a gold-only test set.

Writes fingpt_run/gold_progress.json (live status) and fingpt_run/gold_results.json.
"""
import os, re, json, time, random

os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

OUT = "/home/z/my-project/fingpt_run"
GDIR = os.path.join(OUT, "gold_progress.json")
GENERAL_DIR = os.path.join(OUT, "adapter")
GOLD_DIR = os.path.join(OUT, "adapter_gold")


def save_progress(**kw):
    cur = {}
    try:
        cur = json.load(open(GDIR))
    except Exception:
        pass
    cur.update(kw)
    json.dump(cur, open(GDIR, "w"), ensure_ascii=False)


def main():
    import torch, urllib.request
    torch.set_num_threads(2)
    torch.manual_seed(42)
    from datasets import load_dataset
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    BASE = "Qwen/Qwen2.5-0.5B-Instruct"
    TEMPLATE = "Instruction: {instruction}\nInput: {input}\nAnswer: "
    KW = re.compile(r"\bgold\b|xau|\bgld\b|bullion|precious metal|\bgdx\b", re.I)

    # ---------- 1) filter gold rows ----------
    save_progress(stage="filter_data", status="running")
    tr = load_dataset("FinGPT/fingpt-sentiment-train", split="train")
    gold_train = [dict(r) for r in tr if KW.search(r.get("input") or "")]
    cls = load_dataset("FinGPT/fingpt-sentiment-cls", split="train")
    split = cls.train_test_split(test_size=0.2, shuffle=True, seed=42)
    gold_test = [dict(r) for r in split["test"] if KW.search(r.get("input") or "")][:40]
    from collections import Counter
    label_dist = dict(Counter(r["output"] for r in gold_test))
    save_progress(stage="filter_data", status="done", train_n=len(gold_train), test_n=len(gold_test),
                  keywords="gold / XAU / GLD / GDX / bullion / precious metal")

    # ---------- 2) model + fresh LoRA ----------
    save_progress(stage="load_model", status="running", detail=BASE)
    tok = AutoTokenizer.from_pretrained(BASE)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    try:
        model = AutoModelForCausalLM.from_pretrained(BASE, dtype=torch.bfloat16)
    except TypeError:
        model = AutoModelForCausalLM.from_pretrained(BASE, torch_dtype=torch.bfloat16)
    model.config.use_cache = False
    # start from the GENERAL financial adapter and specialize on gold rows
    # (domain-adaptive continued fine-tuning)
    model = PeftModel.from_pretrained(model, GENERAL_DIR, adapter_name="default")
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    trainable, total = model.get_nb_trainable_parameters()
    save_progress(stage="load_model", status="done", trainable_params=int(trainable), total_params=int(total))

    # ---------- 3) tokenize ----------
    MAXLEN = 128
    def encode(r):
        prompt = TEMPLATE.format(instruction=r.get("instruction") or "", input=r.get("input") or "")
        p_ids = tok(prompt, truncation=True, max_length=MAXLEN)["input_ids"]
        t_ids = tok((r.get("output") or "").strip(), add_special_tokens=False,
                    truncation=True, max_length=8)["input_ids"]
        ids = (p_ids + t_ids + [tok.eos_token_id])[:MAXLEN]
        labels = ([-100] * len(p_ids) + ids[len(p_ids):])[:MAXLEN]
        return {"input_ids": ids, "labels": labels}
    enc_train = [encode(r) for r in gold_train]

    tok.padding_side = "left"
    def norm3(s):
        s = (s or "").strip().lower()
        if "neg" in s: return "negative"
        if "pos" in s: return "positive"
        if "neu" in s: return "neutral"
        return s or "n/a"

    def batch_eval(rows, batch=4, max_new=5):
        preds = []
        model.eval(); model.config.use_cache = True
        for i in range(0, len(rows), batch):
            chunk = rows[i:i + batch]
            prompts = [TEMPLATE.format(instruction=r["instruction"], input=r["input"]) for r in chunk]
            enc = tok(prompts, return_tensors="pt", padding=True, truncation=True, max_length=MAXLEN)
            with torch.no_grad():
                out = model.generate(**enc, max_new_tokens=max_new, do_sample=False, pad_token_id=tok.pad_token_id)
            for j in range(len(chunk)):
                preds.append(tok.decode(out[j][enc["input_ids"].shape[1]:], skip_special_tokens=True).strip())
        model.config.use_cache = False
        oks = [norm3(p) == norm3(r["output"]) for r, p in zip(rows, preds)]
        samples = [{"input": r["input"][:100], "gold": r["output"], "pred": p[:30], "ok": bool(ok)}
                   for r, p, ok in list(zip(rows, preds, oks))[:6]]
        return round(sum(oks) / len(rows), 4), samples

    # reference accuracies on gold test: general adapter + pure base (adapters disabled)
    save_progress(stage="gold_training", status="running", note="eval_reference")
    t = time.time()
    acc_general, _ = batch_eval(gold_test)
    with model.disable_adapter():
        acc_base, _ = batch_eval(gold_test)
    save_progress(stage="gold_training", status="running", general_acc_on_gold=acc_general,
                  base_acc_on_gold=acc_base, eval_seconds=round(time.time() - t))

    # ---------- 4) gold LoRA training ----------
    model.train()
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=2e-4)
    random.seed(42); random.shuffle(enc_train)
    B, ACC = 2, 2
    BUDGET_S, MAX_STEPS = 220, 120
    t0 = time.time(); step = 0; losses = []; ptr = 0
    while step < MAX_STEPS and ptr + B * ACC <= len(enc_train) and (time.time() - t0) < BUDGET_S:
        opt.zero_grad()
        micro = []
        for _ in range(ACC):
            rows = enc_train[ptr:ptr + B]; ptr += B
            mx = max(len(r["input_ids"]) for r in rows)
            ids = torch.tensor([r["input_ids"] + [tok.pad_token_id] * (mx - len(r["input_ids"])) for r in rows])
            lab = torch.tensor([r["labels"] + [-100] * (mx - len(r["labels"])) for r in rows])
            out = model(input_ids=ids, labels=lab)
            (out.loss / ACC).backward()
            micro.append(out.loss.item())
        opt.step()
        step += 1
        L = sum(micro) / len(micro); losses.append(round(L, 4))
        if step == 1 or step % 10 == 0:
            save_progress(stage="gold_training", status="running", step=step, loss=round(L, 4),
                          elapsed_s=round(time.time() - t0))
    save_progress(stage="gold_training", status="done", steps=step,
                  final_loss=round(losses[-1], 4) if losses else None, seconds=round(time.time() - t0))

    # ---------- 5) save gold adapter ----------
    save_progress(stage="save_adapter", status="running")
    model.save_pretrained(GOLD_DIR)
    tok.save_pretrained(GOLD_DIR)
    size_mb = sum(os.path.getsize(os.path.join(GOLD_DIR, f)) for f in os.listdir(GOLD_DIR)) / 2 ** 20
    save_progress(stage="save_adapter", status="done", adapter_mb=round(size_mb, 2))

    # ---------- 6) compare: gold vs general on gold test ----------
    save_progress(stage="eval_gold", status="running")
    t = time.time()
    acc_gold, samples_gold = batch_eval(gold_test)
    model.load_adapter(GENERAL_DIR, adapter_name="general")
    model.set_adapter("general")
    acc_general, _ = batch_eval(gold_test)
    save_progress(stage="eval_gold", status="done", acc_gold=acc_gold, acc_general=acc_general,
                  seconds=round(time.time() - t))

    # ---------- 7) live gold price (COMEX futures via Yahoo) ----------
    price = None
    save_progress(stage="gold_price", status="running")
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?range=3mo&interval=1d"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = json.load(urllib.request.urlopen(req, timeout=15))
        res = data["chart"]["result"][0]
        closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
        price = {"symbol": "GC=F", "currency": "USD",
                 "latest": round(closes[-1], 2),
                 "prev": round(closes[-2], 2) if len(closes) > 1 else None,
                 "series": [round(c, 1) for c in closes],
                 "market_time": res["meta"].get("regularMarketTime")}
        save_progress(stage="gold_price", status="done", latest=price["latest"])
    except Exception as e:
        save_progress(stage="gold_price", status="error", detail=str(e)[:200])

    json.dump({
        "base_model": BASE,
        "keywords": "gold / XAU / GLD / GDX / bullion / precious metal",
        "train_n": len(gold_train), "test_n": len(gold_test), "label_dist": label_dist,
        "training": {"steps": step, "effective_batch": B * ACC, "lr": 2e-4,
                     "seconds": round(time.time() - t0), "loss_curve": losses},
        "eval": {"n": len(gold_test), "acc_base": acc_base, "acc_general": acc_general, "acc_gold": acc_gold},
        "samples": samples_gold,
        "adapter": {"saved": True, "dir": GOLD_DIR, "size_mb": round(size_mb, 2)},
        "price": price,
    }, open(os.path.join(OUT, "gold_results.json"), "w"), ensure_ascii=False, indent=2)
    save_progress(stage="done", status="done", acc_base=acc_base, acc_general=acc_general, acc_gold=acc_gold)
    print("GOLD FINISHED base=%.4f general=%.4f gold=%.4f" % (acc_base, acc_general, acc_gold))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        save_progress(stage="error", status="error", detail=traceback.format_exc()[-600:])
        raise
