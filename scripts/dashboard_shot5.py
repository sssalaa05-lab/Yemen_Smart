"""Lightest possible capture of GenAI Brief: block heavy assets, fast shot."""
from playwright.sync_api import sync_playwright

OUT = "/home/z/my-project/download/nexus-local-genai-brief.png"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=[
        "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage",
        "--single-process",
    ])
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    # block the heavy TradingView iframe + websocket streams
    page.route("**/tradingview*/**", lambda r: r.abort())
    page.route("**/chart-storage**", lambda r: r.abort())
    page.goto("http://localhost:3000/", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(9000)
    try:
        page.locator("text=GENAI BRIEF").first.scroll_into_view_if_needed(timeout=5000)
        page.wait_for_timeout(3000)
    except Exception as e:
        print("locator:", e)
    page.screenshot(path=OUT)
    browser.close()
print("saved", OUT)
