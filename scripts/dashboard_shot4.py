"""Scroll precisely to the GenAI Brief panel and capture it."""
from playwright.sync_api import sync_playwright

OUT = "/home/z/my-project/download/nexus-local-genai-brief.png"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=[
        "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage",
    ])
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.goto("http://localhost:3000/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(15000)
    # find the GENAI BRIEF heading and bring it into view
    try:
        el = page.locator("text=GENAI BRIEF").first
        el.scroll_into_view_if_needed(timeout=8000)
    except Exception as e:
        print("locator failed:", e)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.55)")
    page.wait_for_timeout(5000)
    page.screenshot(path=OUT)
    browser.close()
print("saved", OUT)
