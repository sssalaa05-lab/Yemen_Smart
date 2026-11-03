import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import os from "os";
import path from "path";
import { execSync } from "child_process";

export const dynamic = "force-dynamic";

async function readJson(p: string): Promise<unknown> {
  try {
    return JSON.parse(await fs.readFile(p, "utf8"));
  } catch {
    return null;
  }
}

function sh(cmd: string): string {
  try {
    return execSync(cmd, { encoding: "utf8", timeout: 4000 }).trim();
  } catch {
    return "";
  }
}

export async function GET() {
  const root = "/home/z/my-project";
  const [progress, results, verified, goldProgress, goldResults, goldTest] = await Promise.all([
    readJson(path.join(root, "fingpt_run", "progress.json")),
    readJson(path.join(root, "fingpt_run", "results.json")),
    readJson(path.join(root, "fingpt_run", "verified.json")),
    readJson(path.join(root, "fingpt_run", "gold_progress.json")),
    readJson(path.join(root, "fingpt_run", "gold_results.json")),
    readJson(path.join(root, "fingpt_run", "gold_test_set.json")),
  ]);

  const repo = {
    url: sh(`git -C ${root}/FinGPT remote get-url origin`),
    commit: sh(`git -C ${root}/FinGPT log --oneline -1`),
    exists: sh(`test -d ${root}/FinGPT/.git && echo yes || echo no`) === "yes",
  };

  const sys = {
    platform: os.platform(),
    arch: os.arch(),
    cpus: os.cpus().length,
    ram_gb: +(os.totalmem() / 2 ** 30).toFixed(1),
    node: process.version,
  };

  return NextResponse.json({ progress, results, verified, goldProgress, goldResults, goldTest, repo, sys, ts: Date.now() });
}
