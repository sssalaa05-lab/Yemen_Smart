#!/bin/bash
# Nexus Trader — unified startup for the sandbox runtime
# Runs under `bun run dev` (system-managed process tree on port 3000)

NEXUS_ROOT="/home/z/my-project/nexus-system/Nexus-Trading-System-MT5-main"

# 1) Make sure Redis is up (daemonized instance survives independently)
if ! python3 -c "import socket;socket.create_connection(('127.0.0.1',6379),timeout=2)" 2>/dev/null; then
  /home/z/my-project/scripts/bin/redis-server --port 6379 --save "" --appendonly no --daemonize yes
  sleep 1
fi

# 2) Launch the 9-service Python fleet (supervisor auto-restarts crashes)
cd "$NEXUS_ROOT"
nohup .venv/bin/python run.py --paper --no-frontend > /tmp/nexus_run.log 2>&1 &
NEXUS_FLEET_PID=$!
echo "[nexus-launcher] fleet supervisor PID $NEXUS_FLEET_PID"

# 3) Dashboard (Next.js production build) in the foreground on port 3000
cd "$NEXUS_ROOT/dashboard"
exec ./node_modules/.bin/next start -p 3000
