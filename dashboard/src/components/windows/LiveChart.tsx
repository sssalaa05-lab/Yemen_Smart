'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import NeonCard from '../shared/NeonCard';
import type { Timeframe } from '../../types';
import { useDashboardStore } from '@/stores/dashboardStore';

const TIMEFRAMES: Timeframe[] = ['M1', 'M5', 'M15', 'H1', 'H4'];

interface Candle {
  time: number; // epoch seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/** Aggregate M5 candles into a higher timeframe (minutes). */
function aggregate(candles: Candle[], minutes: number): Candle[] {
  if (minutes <= 5) return candles;
  const bucketSec = minutes * 60;
  const map = new Map<number, Candle>();
  for (const c of candles) {
    const key = Math.floor(c.time / bucketSec) * bucketSec;
    const cur = map.get(key);
    if (!cur) {
      map.set(key, { ...c, time: key });
    } else {
      cur.high = Math.max(cur.high, c.high);
      cur.low = Math.min(cur.low, c.low);
      cur.close = c.close;
      cur.volume += c.volume;
    }
  }
  return [...map.values()].sort((a, b) => a.time - b.time);
}

function drawChart(
  canvas: HTMLCanvasElement,
  candles: Candle[],
  symbol: string,
) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const padL = 8;
  const padR = 64;
  const padT = 14;
  const padB = 22;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;

  ctx.font = '10px monospace';
  ctx.textBaseline = 'middle';

  if (!candles.length) {
    ctx.fillStyle = 'rgba(160,170,190,0.55)';
    ctx.textAlign = 'center';
    ctx.fillText('connecting to nexus feed…', w / 2, h / 2);
    return;
  }

  const lows = Math.min(...candles.map((c) => c.low));
  const highs = Math.max(...candles.map((c) => c.high));
  const span = highs - lows || highs * 0.001 || 1;
  const min = lows - span * 0.08;
  const max = highs + span * 0.08;
  const y = (p: number) => padT + ((max - p) / (max - min)) * plotH;
  const step = plotW / candles.length;
  const bodyW = Math.max(1.5, Math.min(9, step * 0.62));

  // horizontal grid + right price axis
  ctx.textAlign = 'left';
  for (let i = 0; i <= 4; i++) {
    const p = min + ((max - min) * i) / 4;
    const yy = y(p);
    ctx.strokeStyle = 'rgba(120,130,160,0.10)';
    ctx.beginPath();
    ctx.moveTo(padL, yy);
    ctx.lineTo(padL + plotW, yy);
    ctx.stroke();
    ctx.fillStyle = 'rgba(150,160,185,0.75)';
    ctx.fillText(p.toFixed(2), padL + plotW + 8, yy);
  }

  // time axis labels (start / mid / end)
  ctx.textAlign = 'center';
  ctx.fillStyle = 'rgba(150,160,185,0.6)';
  const fmt = (t: number) => {
    const d = new Date(t * 1000);
    return `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`;
  };
  [0, Math.floor(candles.length / 2), candles.length - 1].forEach((idx, k) => {
    const xx = padL + idx * step + step / 2;
    ctx.fillText(fmt(candles[idx].time), Math.min(Math.max(xx, 24), w - 30), h - 9);
    void k;
  });

  // candles
  candles.forEach((c, i) => {
    const cx = padL + i * step + step / 2;
    const up = c.close >= c.open;
    const col = up ? '#22e5a1' : '#ff4d6d';
    ctx.strokeStyle = col;
    ctx.fillStyle = col;
    // wick
    ctx.beginPath();
    ctx.moveTo(cx, y(c.high));
    ctx.lineTo(cx, y(c.low));
    ctx.lineWidth = 1;
    ctx.stroke();
    // body
    const yO = y(c.open);
    const yC = y(c.close);
    const top = Math.min(yO, yC);
    const bh = Math.max(1, Math.abs(yC - yO));
    ctx.fillRect(cx - bodyW / 2, top, bodyW, bh);
  });

  // last price line + tag
  const last = candles[candles.length - 1];
  const lastUp = last.close >= candles[Math.max(0, candles.length - 2)].open;
  const ly = y(last.close);
  ctx.setLineDash([4, 3]);
  ctx.strokeStyle = lastUp ? 'rgba(34,229,161,0.6)' : 'rgba(255,77,109,0.6)';
  ctx.beginPath();
  ctx.moveTo(padL, ly);
  ctx.lineTo(padL + plotW, ly);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = lastUp ? '#0d2b22' : '#2b0d14';
  ctx.fillRect(padL + plotW + 2, ly - 8, padR - 6, 16);
  ctx.strokeStyle = lastUp ? '#22e5a1' : '#ff4d6d';
  ctx.strokeRect(padL + plotW + 2, ly - 8, padR - 6, 16);
  ctx.fillStyle = lastUp ? '#22e5a1' : '#ff4d6d';
  ctx.textAlign = 'left';
  ctx.fillText(last.close.toFixed(2), padL + plotW + 7, ly);

  // watermark
  ctx.fillStyle = 'rgba(140,150,180,0.28)';
  ctx.textAlign = 'left';
  ctx.fillText(`${symbol} · NEXUS FEED (Yahoo GC=F)`, padL + 4, padT + 2);
}

export default function li() {
  const selectedSymbol = useDashboardStore((s) => s.symbol);
  const activeTimeframe = useDashboardStore((s) => s.timeframe);
  const setSymbol = useDashboardStore((s) => s.setSymbol);
  const setTimeframe = useDashboardStore((s) => s.setTimeframe);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const rawRef = useRef<Candle[]>([]);
  const [showSymbolPicker, setShowSymbolPicker] = useState(false);
  const [feedOk, setFeedOk] = useState<boolean | null>(null);

  const tfMinutes: Record<string, number> = {
    M1: 5, // Yahoo free feed starts at 5m — M1 renders the 5m window
    M5: 5,
    M15: 15,
    H1: 60,
    H4: 240,
  };

  const render = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const mins = tfMinutes[activeTimeframe] ?? 5;
    const view = aggregate(rawRef.current, mins).slice(-160);
    drawChart(canvas, view, selectedSymbol);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTimeframe, selectedSymbol]);

  const load = useCallback(async () => {
    try {
      const res = await fetch(
        `/api/v2/market/candles?symbol=${encodeURIComponent(selectedSymbol)}&timeframe=M5&count=500`,
        { cache: 'no-store' },
      );
      const body = await res.json();
      const rows: Array<Record<string, unknown>> = body?.data ?? [];
      const parsed: Candle[] = rows
        .map((r) => ({
          time: Math.floor(new Date(String(r.timestamp)).getTime() / 1000),
          open: Number(r.open),
          high: Number(r.high),
          low: Number(r.low),
          close: Number(r.close),
          volume: Number(r.volume) || 0,
        }))
        .filter((c) => Number.isFinite(c.close) && c.close > 0)
        .sort((a, b) => a.time - b.time);
      rawRef.current = parsed;
      setFeedOk(parsed.length > 0);
    } catch {
      setFeedOk(false);
    }
    render();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSymbol, render]);

  useEffect(() => {
    load();
    const iv = setInterval(load, 30_000);
    const onResize = () => render();
    window.addEventListener('resize', onResize);
    return () => {
      clearInterval(iv);
      window.removeEventListener('resize', onResize);
    };
  }, [load, render]);

  const SYMBOLS = ['XAUUSD', 'BTCUSD', 'EURUSD'];

  return (
    <NeonCard
      title="Live Chart"
      glow="cyan"
      noPadding
      icon={
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M3 3v18h18" />
          <path d="M7 16l4-8 4 4 4-12" />
        </svg>
      }
      headerRight={
        <div className="flex items-center gap-3">
          <span
            className={`rounded px-1.5 py-0.5 text-[9px] font-mono font-bold tracking-wider ${
              feedOk === false
                ? 'bg-red-500/15 text-red-400'
                : 'bg-emerald-500/15 text-emerald-400'
            }`}
          >
            {feedOk === false ? 'FEED OFFLINE' : 'NEXUS FEED · REAL'}
          </span>
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowSymbolPicker(!showSymbolPicker)}
              className="flex items-center gap-1 rounded bg-bg-secondary px-2 py-1 text-xs font-mono text-neon-cyan hover:bg-bg-tertiary transition-colors"
            >
              {selectedSymbol}
              <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><path d="M7 10l5 5 5-5z" /></svg>
            </button>
            {showSymbolPicker && (
              <div className="absolute left-0 top-full z-50 mt-1 rounded border border-border-primary/20 bg-bg-primary shadow-lg">
                {SYMBOLS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => {
                      setSymbol(s);
                      setShowSymbolPicker(false);
                    }}
                    className={`block w-full px-3 py-1.5 text-left text-xs font-mono hover:bg-bg-tertiary transition-colors ${
                      s === selectedSymbol ? 'text-neon-cyan' : 'text-text-secondary'
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      }
      className="h-full min-h-0 flex flex-col"
    >
      <div className="flex items-center gap-1 border-b border-border-primary/10 px-3 py-1 shrink-0">
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf}
            type="button"
            onClick={() => setTimeframe(tf)}
            className={`rounded px-2.5 py-1 text-[11px] font-mono font-semibold transition-all ${
              tf === activeTimeframe
                ? 'bg-neon-purple/15 text-neon-purple'
                : 'text-text-muted hover:text-text-secondary hover:bg-bg-tertiary'
            }`}
          >
            {tf}
          </button>
        ))}
      </div>

      <div className="relative flex-1 min-h-0 w-full">
        <canvas
          ref={canvasRef}
          className="absolute inset-0 h-full w-full"
          style={{ display: 'block' }}
        />
      </div>
    </NeonCard>
  );
}
