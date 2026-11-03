import { NextResponse } from "next/server";
import { spawn } from "child_process";

export const dynamic = "force-dynamic";
export const maxDuration = 120;

const PORT = 8766;
const BASE = `http://127.0.0.1:${PORT}`;
const SCRIPT = "/home/z/my-project/scripts/fingpt_serve.py";

let spawning: Promise<void> | null = null;

function ensureDaemon(): Promise<void> {
  if (!spawning) {
    const child = spawn("python3", ["-u", SCRIPT], {
      env: { ...process.env, HF_ENDPOINT: "https://hf-mirror.com" },
      stdio: "ignore",
      detached: true,
    });
    child.unref();
    spawning = new Promise<void>((resolve) => {
      child.on("error", () => resolve());
      setTimeout(resolve, 1000);
    });
    // allow re-spawn on later requests if the daemon dies
    setTimeout(() => { spawning = null; }, 8000);
  }
  return spawning;
}

async function health(timeoutMs = 1200): Promise<{ status?: string; error?: string } | null> {
  try {
    const r = await fetch(`${BASE}/health`, {
      signal: AbortSignal.timeout(timeoutMs),
      cache: "no-store",
    });
    return await r.json();
  } catch {
    return null;
  }
}

export async function POST(req: Request) {
  let text = "";
  let model: string | undefined;
  try {
    const b = await req.json();
    text = String(b?.text ?? "").trim();
    model = typeof b?.model === "string" ? b.model : undefined;
  } catch { /* ignore body errors */ }
  if (!text) {
    return NextResponse.json({ error: "أدخل نصاً للتحليل" }, { status: 400 });
  }

  let h = await health();
  if (!h) {
    await ensureDaemon();
    const t0 = Date.now();
    while (Date.now() - t0 < 90_000) {
      await new Promise((r) => setTimeout(r, 1500));
      h = await health();
      if (h?.status === "ready" || h?.status === "error") break;
    }
  }
  if (!h) {
    return NextResponse.json({ error: "لم تبدأ خدمة الاستدلال — أعد المحاولة" }, { status: 503 });
  }
  if (h.status === "error") {
    return NextResponse.json({ error: h.error || "خطأ في تحميل النموذج" }, { status: 500 });
  }

  try {
    const r = await fetch(`${BASE}/predict`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text.slice(0, 2000), model }),
      signal: AbortSignal.timeout(60_000),
    });
    return NextResponse.json(await r.json());
  } catch {
    return NextResponse.json({ error: "فشل الاتصال بخدمة الاستدلال" }, { status: 502 });
  }
}
