"""Scroll down and capture GenAI Brief panel."""
from playwright.sync_api import sync_playwright

OUT = "/home/z/my-project/download/nexus-local-genai-brief.png"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=[
        "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage",
        "--js-flags=--max-old-space-size=256",
    ])
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.goto("http://localhost:3000/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(12000)
    # scroll to the bottom row where GenAI Brief lives
    page.mouse.wheel(0, 2500)
    page.wait_for_timeout(5000)
    page.screenshot(path=OUT)
    browser.close()
print("saved", OUT)
