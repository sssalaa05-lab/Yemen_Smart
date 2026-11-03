#!/usr/bin/env python3
"""FinGPT run on CPU: official FinGPT pipeline (instruction LoRA fine-tuning for
financial sentiment analysis) on a small base model, following the repo's
FinGPT_Benchmark prompt template + FinGPT_Sentiment_Analysis_v3 methodology.

Writes fingpt_run/progress.json (live status) and fingpt_run/results.json (final).
"""
import os, json, time, random

os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

OUT = "/home/z/my-project/fingpt_run"
os.makedirs(OUT, exist_ok=True)

def save_progress(**kw):
    p = os.path.join(OUT, "progress.json")
    cur = {}
    if os.path.exists(p):
        try: cur = json.load(open(p))
        except Exception: pass
    cur.update(kw)
    json.dump(cur, open(p, "w"), ensure_ascii=False)

def save_result(obj):
    json.dump(obj, open(os.path.join(OUT, "results.json"), "w"), ensure_ascii=False, indent=2)

def main():
    import torch
    torch.set_num_threads(2)
    torch.manual_seed(42)
    from datasets import load_dataset
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig, get_peft_model

    BASE = "Qwen/Qwen2.5-0.5B-Instruct"
    TEMPLATE = "Instruction: {instruction}\nInput: {input}\nAnswer: "  # official FinGPT template

    # ---------- 1) data ----------
    save_progress(stage="download_data", status="running", detail="FinGPT/fingpt-sentiment-train + FinGPT/fingpt-sentiment-cls")
    train_raw = load_dataset("FinGPT/fingpt-sentiment-train", split="train[:600]")
    cls_full = load_dataset("FinGPT/fingpt-sentiment-cls", split="train")
    # same as FinGPT_Benchmark/utils.py load_dataset(): create test split if missing
    cls_split = cls_full.train_test_split(test_size=0.2, shuffle=True, seed=42)
    save_progress(stage="download_data", status="done", train_n=len(train_raw), test_n=len(cls_split["test"]))

    def norm(r):
        return {"instruction": r.get("instruction") or "", "input": r.get("input") or "",
                "output": (r.get("output") or "").strip()}
    train_rows = [norm(r) for r in train_raw]
    test_rows = [norm(r) for r in list(cls_split["test"])[:30]]

    # ---------- 2) model + LoRA ----------
    save_progress(stage="load_model", status="running", detail=BASE)
    tok = AutoTokenizer.from_pretrained(BASE)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    try:
        model = AutoModelForCausalLM.from_pretrained(BASE, dtype=torch.bfloat16)
    except TypeError:
        model = AutoModelForCausalLM.from_pretrained(BASE, torch_dtype=torch.bfloat16)
    model.config.use_cache = False
    lora_cfg = LoraConfig(r=8, lora_alpha=16, lora_dropout=0.05,
                          target_modules=["q_proj", "k_proj", "v_proj"], task_type="CAUSAL_LM")
    model = get_peft_model(model, lora_cfg)
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    trainable, total = model.get_nb_trainable_parameters()
    save_progress(stage="load_model", status="done", trainable_params=int(trainable), total_params=int(total))

    # ---------- 3) tokenize (FinGPT_Benchmark/utils.py logic) ----------
    MAXLEN = 128
    def encode(r):
        prompt = TEMPLATE.format(instruction=r["instruction"], input=r["input"])
        p_ids = tok(prompt, truncation=True, max_length=MAXLEN)["input_ids"]
        t_ids = tok(r["output"], add_special_tokens=False, truncation=True, max_length=8)["input_ids"]
        ids = (p_ids + t_ids + [tok.eos_token_id])[:MAXLEN]
        labels = ([-100] * len(p_ids) + ids[len(p_ids):])[:MAXLEN]
        return {"input_ids": ids, "labels": labels}
    enc_train = [encode(r) for r in train_rows]

    # ---------- helpers: eval ----------
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
                txt = tok.decode(out[j][enc["input_ids"].shape[1]:], skip_special_tokens=True)
                preds.append(txt.strip())
        model.config.use_cache = False
        correct = 0; samples = []
        for r, p in zip(rows, preds):
            ok = norm3(p) == norm3(r["output"])
            correct += ok
            if len(samples) < 8:
                samples.append({"input": r["input"][:110], "gold": r["output"], "pred": p[:40], "ok": bool(ok)})
        return round(correct / len(rows), 4), samples

    save_progress(stage="baseline_eval", status="running")
    t = time.time()
    acc_before, samples_before = batch_eval(test_rows)
    save_progress(stage="baseline_eval", status="done", acc_baseline=acc_before, seconds=round(time.time() - t))

    # ---------- 4) LoRA training ----------
    save_progress(stage="training", status="running")
    model.train()
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=2e-4)
    random.seed(42); random.shuffle(enc_train)
    B, ACC = 2, 2  # effective batch = 4
    BUDGET_S, MAX_STEPS = 240, 110
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
            save_progress(stage="training", status="running", step=step, loss=round(L, 4), elapsed_s=round(time.time() - t0))
    save_progress(stage="training", status="done", steps=step, final_loss=round(losses[-1], 4) if losses else None, seconds=round(time.time() - t0))

    # ---------- 4.5) export LoRA adapter for live inference ----------
    save_progress(stage="export_adapter", status="running")
    t = time.time()
    ADAPTER_DIR = os.path.join(OUT, "adapter")
    model.save_pretrained(ADAPTER_DIR)
    tok.save_pretrained(ADAPTER_DIR)
    n_files = len(os.listdir(ADAPTER_DIR))
    size_mb = sum(os.path.getsize(os.path.join(ADAPTER_DIR, f)) for f in os.listdir(ADAPTER_DIR)) / 2 ** 20
    save_progress(stage="export_adapter", status="done", adapter_dir=ADAPTER_DIR, adapter_files=n_files, adapter_mb=round(size_mb, 2))

    # ---------- 5) finetuned eval ----------
    save_progress(stage="finetuned_eval", status="running")
    t = time.time()
    acc_after, samples_after = batch_eval(test_rows)
    save_progress(stage="finetuned_eval", status="done", acc_final=acc_after, seconds=round(time.time() - t))

    save_result({
        "base_model": BASE, "lora": {"r": 8, "alpha": 16, "targets": ["q_proj", "k_proj", "v_proj"],
                                     "trainable_params": int(trainable), "total_params": int(total)},
        "adapter": {"saved": True, "dir": ADAPTER_DIR, "files": n_files, "size_mb": round(size_mb, 2),
                    "instruction": "What is the sentiment of this news? Please choose from: negative / neutral / positive."},
        "template": TEMPLATE, "datasets": {"train": "FinGPT/fingpt-sentiment-train[:600]",
                                           "test": "FinGPT/fingpt-sentiment-cls[:40]"},
        "training": {"steps": step, "effective_batch": B * ACC, "lr": 2e-4, "seconds": round(time.time() - t0),
                     "loss_curve": losses},
        "eval": {"n": len(test_rows), "acc_before": acc_before, "acc_after": acc_after},
        "samples_before": samples_before, "samples_after": samples_after,
        "hardware": {"device": "cpu", "threads": 2},
    })
    save_progress(stage="done", status="done", acc_baseline=acc_before, acc_final=acc_after)
    print("FINISHED", acc_before, "->", acc_after)

if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        save_progress(stage="error", status="error", detail=traceback.format_exc()[-600:])
        raise
