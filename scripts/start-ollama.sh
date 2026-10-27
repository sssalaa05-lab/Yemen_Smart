#!/bin/bash
# ══════════════════════════════════════════════════════════════════
# Nexus — Local AI (Ollama) launcher
# Starts Ollama server with qwen2.5:0.5b on port 11434 (CPU-only).
# The GenAI agents (nexus-agents :9004) detect it automatically via
# NEXUS_LLM_PROVIDER=local in .env — no API key, 100% offline.
# ══════════════════════════════════════════════════════════════════
BASE=/home/z/my-project/ollama
export LD_LIBRARY_PATH=$BASE/lib/ollama
export OLLAMA_MODELS=$BASE/models
export OLLAMA_NUM_PARALLEL=2
export OLLAMA_KEEP_ALIVE=15m
export OLLAMA_MAX_LOADED_MODELS=1

if curl -s --max-time 2 http://localhost:11434/api/version > /dev/null; then
  echo "Ollama already running:"
  curl -s http://localhost:11434/api/version
  echo ""
else
  cd $BASE && python3 /home/z/my-project/scripts/daemonize.py /tmp/ollama-serve.log ./bin/ollama serve
  sleep 3
  echo "Ollama started: $(curl -s http://localhost:11434/api/version)"
fi

echo "Installed models:"
curl -s http://localhost:11434/api/tags | python3 -c "import sys,json; [print(' -', m['name']) for m in json.load(sys.stdin).get('models',[])]"
