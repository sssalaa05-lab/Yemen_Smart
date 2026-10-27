"""Switch runtime llm_provider to local (Ollama) in Redis, preserving other keys."""
import json
import redis

r = redis.Redis(host="localhost", port=6379, decode_responses=True)
raw = r.get("nexus:runtime:settings")
d = json.loads(raw) if raw else {}
old = d.get("llm_provider")
d["llm_provider"] = "local"
r.set("nexus:runtime:settings", json.dumps(d))
print(f"llm_provider: {old!r} -> 'local'")
print("total keys in runtime settings:", len(d))
