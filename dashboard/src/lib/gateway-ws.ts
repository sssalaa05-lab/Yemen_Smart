/**
 * Native WebSocket URLs for the nexus-api gateway (FastAPI), e.g. `/ws/ticks`.
 * Use NEXT_PUBLIC_WS_GATEWAY_URL as the origin only (no `/ws/...` suffix).
 *
 * Default: same-origin at runtime — next.config.js rewrites /ws/* to the
 * gateway, so this works locally AND behind preview proxies (no hardcoded
 * localhost URL baked into the bundle).
 */
export function gatewayWsUrl(path: string): string {
  const envRoot = (process.env.NEXT_PUBLIC_WS_GATEWAY_URL || '').replace(/\/$/, '');
  let root = envRoot;
  if (!root && typeof window !== 'undefined') {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    root = `${proto}//${window.location.host}`;
  }
  if (!root) {
    root = 'ws://127.0.0.1:9000';
  }
  const p = path.startsWith('/') ? path : `/${path}`;
  const withWs = p.startsWith('/ws') ? p : `/ws${p}`;
  return `${root}${withWs}`;
}
