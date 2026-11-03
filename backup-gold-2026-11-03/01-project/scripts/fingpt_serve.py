#!/usr/bin/env python3
"""FinGPT live inference daemon (CPU).

Loads Qwen2.5-0.5B-Instruct once with TWO LoRA adapters:
  - "general": trained on the full FinGPT sentiment sample
  - "gold":    trained only on gold-market rows (fingpt_run/adapter_gold)
Serves:
  GET  /health   -> {"status": "loading"|"ready"|"error", "adapters": {...}}
  POST /predict  {"text": "...", "model": "general"|"gold"}
             -> {"pred", "raw", "latency_ms", "adapter"[, "pred_general"]}
Follows the official FinGPT_Benchmark prompt template.
"""
import os, json, time, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

PORT = 8766
BASE = "Qwen/Qwen2.5-0.5B-Instruct"
GENERAL = "/home/z/my-project/fingpt_run/adapter"
GOLD = "/home/z/my-project/fingpt_run/adapter_gold"
STATUS_FILE = "/home/z/my-project/fingpt_run/serve_status.json"
TEMPLATE = "Instruction: {instruction}\nInput: {input}\nAnswer: "
INSTRUCTION = ("What is the sentiment of this news? "
               "Please choose from: negative / neutral / positive.")

state = {"status": "loading", "adapters": {}, "error": None, "loaded_at": None, "pid": os.getpid()}
lock = threading.Lock()
model = None
tok = None


def save_status():
    try:
        json.dump(state, open(STATUS_FILE, "w"), ensure_ascii=False)
    except Exception:
        pass


def norm3(s):
    s = (s or "").strip().lower()
    if "neg" in s: return "negative"
    if "pos" in s: return "positive"
    if "neu" in s: return "neutral"
    return s or "n/a"


def load():
    global model, tok
    import torch
    torch.set_num_threads(2)
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(BASE)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    try:
        model = AutoModelForCausalLM.from_pretrained(BASE, dtype=torch.bfloat16)
    except TypeError:
        model = AutoModelForCausalLM.from_pretrained(BASE, torch_dtype=torch.bfloat16)
    model.config.use_cache = True
    from peft import PeftModel
    model = PeftModel.from_pretrained(model, GENERAL, adapter_name="general")
    state["adapters"]["general"] = True
    if os.path.isdir(GOLD):
        model.load_adapter(GOLD, adapter_name="gold")
        state["adapters"]["gold"] = True
    model.eval()
    state["status"] = "ready"
    state["loaded_at"] = time.time()
    save_status()


def load_safe():
    try:
        load()
    except Exception as e:
        state["status"] = "error"
        state["error"] = str(e)[:500]
        save_status()


def predict(text, which="general"):
    import torch
    name = which if which in state["adapters"] else "general"
    t0 = time.time()
    prompt = TEMPLATE.format(instruction=INSTRUCTION, input=text)
    enc = tok(prompt, return_tensors="pt", truncation=True, max_length=256)
    with lock, torch.no_grad():
        model.set_adapter(name)
        out = model.generate(**enc, max_new_tokens=6, do_sample=False, pad_token_id=tok.pad_token_id)
    txt = tok.decode(out[0][enc["input_ids"].shape[1]:], skip_special_tokens=True)
    return {"pred": norm3(txt), "raw": txt.strip()[:80],
            "latency_ms": int((time.time() - t0) * 1000), "adapter": name}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep logs quiet
        pass

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        if self.path == "/health":
            self._send(200, state)
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/predict":
            return self._send(404, {"error": "not found"})
        if state["status"] != "ready":
            return self._send(503, state)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n) or b"{}")
            text = (req.get("text") or "").strip()
            if not text:
                return self._send(400, {"error": "empty text"})
            which = "gold" if req.get("model") == "gold" else "general"
            res = predict(text[:2000], which)
            if which == "gold":
                res["pred_general"] = predict(text[:2000], "general")["pred"]
            self._send(200, res)
        except Exception as e:
            self._send(500, {"error": str(e)[:300]})


if __name__ == "__main__":
    save_status()
    threading.Thread(target=load_safe, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
