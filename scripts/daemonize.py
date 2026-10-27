#!/usr/bin/env python3
"""Double-fork daemonizer — same escape technique redis --daemonize uses.

Usage: python3 daemonize.py <logfile> <command> [args...]
The child is reparented to init (PID 1) with a fresh session, so nothing
walking the tool-shell's process tree can reap it.
"""
import os
import sys


def daemonize(argv) -> None:
    pid = os.fork()
    if pid > 0:
        os._exit(0)                      # first parent exits immediately
    os.setsid()                          # detach from controlling terminal
    pid = os.fork()
    if pid > 0:
        os._exit(0)                      # intermediate exits -> child reparents to init
    sys.stdout.flush()
    sys.stderr.flush()
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    os.execvp(argv[0], argv)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: daemonize.py <logfile> <cmd> [args...]", file=sys.stderr)
        sys.exit(2)
    logfile = sys.argv[1]
    cmd = sys.argv[2:]
    fd = os.open(logfile, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    daemonize(["/bin/sh", "-c", "exec " + " ".join(f"'{a}'" if " " in a else a for a in cmd) + f" >> '{logfile}' 2>&1"])
