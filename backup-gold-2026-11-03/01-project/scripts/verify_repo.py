#!/usr/bin/env python3
"""Re-verify the FinGPT repo components in THIS sandbox and save verified.json
for the dashboard (fast, no LLM loading)."""
import json, subprocess, datetime

def run(cmd, cwd=None, timeout=240):
    try:
        r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return f"ERROR: {e}"

root = "/home/z/my-project/FinGPT"

pytest_out = run("python3 -m pytest tests/ -q 2>&1 | tail -1", cwd=root)
forex_out = run("python3 fingpt/FinGPT_ForexIntelligence/test_basic.py 2>&1 | grep -E 'Passed:'", cwd=root)
cloud_out = run("python3 cloud_test_fingpt.py 2>/dev/null | grep -cE '^\\[\\+\\]'", cwd=root)
torch_ver = run("python3 -c 'import torch;print(torch.__version__)'").strip()
tf_ver = run("python3 -c 'import transformers;print(transformers.__version__)'").strip()

verified = {
    "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    "pytest": pytest_out,
    "forex": forex_out,
    "packages_ok": cloud_out + " حزمة أساسية (سكربت التحقق الرسمي cloud_test_fingpt.py)",
    "torch": torch_ver,
    "transformers": tf_ver,
}
json.dump(verified, open("/home/z/my-project/fingpt_run/verified.json", "w"), ensure_ascii=False, indent=2)
print(json.dumps(verified, ensure_ascii=False, indent=2))
