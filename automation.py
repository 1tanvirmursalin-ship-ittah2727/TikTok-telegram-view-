# automation.py -- Playwright view sender (config-driven, speed optimized)
# Imports CONFIG for all delay/timeout values; tracks run duration.

import asyncio
import os
import random
import time
from typing import Callable, Optional, Awaitable

from playwright.async_api import async_playwright, BrowserContext, Page
from proxy_manager import get_fresh_proxy
from fingerprint import get_random_fingerprint, get_fingerprint_js
from fake_useragent import UserAgent

# Termux: Playwright নিজের বাইনারি ডাউনলোড না করুক
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

CHROMIUM_PATH = "/data/data/com.termux/files/usr/bin/chromium-browser"

_ua_gen = UserAgent()

ProgressCB = Optional[Callable[[str], Awaitable[None]]]


# ── Config-aware delay ────────────────────────────────────────────
async def _delay(min_ms: Optional[int] = None, max_ms: Optional[int] = None):
    from config import CONFIG
    lo = min_ms if min_ms is not None else CONFIG.min_delay_ms
    hi = max_ms if max_ms is not None else CONFIG.max_delay_ms
    await asyncio.sleep(random.uniform(lo / 1000, hi / 1000))


# ── Helper: try multiple selectors ───────────────────────────────
async def _try_selectors(
    page: Page,
    selectors: list[str],
    timeout_each: int = 4000,
) -> Optional[object]:
    for sel in selectors:
        try:
            elem = await page.wait_for_selector(sel, timeout=timeout_each)
            if elem:
                return elem
        except Exception:
            continue
    return None


# ── Main view-send coroutine ──────────────────────────────────────
async def send_views(
    tiktok_url: str,
    progress_callback: ProgressCB = None,
) -> dict:
    """
    One full run:
      fresh proxy → fingerprint → browser context → leofame submit
    Returns: {"success": bool, "message": str, "proxy": str|None, "duration": float}
    """
    from config import CONFIG
    t_start = time.time()

    async def _cb(text: str):
        if progress_callback:
            try:
                await progress_callback(text)
            except Exception:
                pass

    # ── 1. Proxy ─────────────────────────────────────────────────
    await _cb("🌐 Finding proxy…")
    proxy_url = await get_fresh_proxy()
    if not proxy_url:
        return {
            "success": False,
            "message": "❌ No alive proxy found. Pool exhausted.",
            "proxy": None,
            "duration": time.time() - t_start,
        }

    # ── 2. Fingerprint ───────────────────────────────────────────
    fp          = get_random_fingerprint()
    user_agent  = _ua_gen.random
    fp_js       = get_fingerprint_js(fp)
    proxy_cfg   = {"server": proxy_url}

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.launch(
                executable_path=CHROMIUM_PATH,
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--disable-sync",
                    "--disable-translate",
                    "--disable-features=TranslateUI",
                    "--metrics-recording-only",
                    "--no-first-run",
                    "--safebrowsing-disable-auto-update",
                    "--single-process",
                    f"--lang={fp['language']}",
                ],
            )
        except Exception as e:
            return {
                "success": False,
                "message": f"❌ Browser launch failed: {str(e)[:120]}",
                "proxy": proxy_url,
                "duration": time.time() - t_start,
            }

        context: BrowserContext = await browser.new_context(
            proxy=proxy_cfg,
            user_agent=user_agent,
            viewport={"width": fp["resolution"][0], "height": fp["resolution"][1]},
            locale=fp["language"],
            timezone_id=fp["timezone"],
            color_scheme="dark",
            java_script_enabled=True,
            bypass_csp=True,
            ignore_https_errors=True,
        )
        await context.add_init_script(fp_js)
        page: Page = await context.new_page()

        # Block heavy resources (speed up page load)
        await page.route(
            "**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,otf}",
            lambda route: route.abort(),
        )
        await page.route(
            "**/analytics/**", lambda route: route.abort()
        )
        await page.route(
            "**/gtag/**",      lambda route: route.abort()
        )

        try:
            # ── 3. Navigate ──────────────────────────────────────
            await _cb(f"🌐 Opening leofame… (proxy: {proxy_url[-20:]})")
            await page.goto(
                "https://leofame.com/free-tiktok-views",
                wait_until="domcontentloaded",
                timeout=CONFIG.page_timeout,
            )
            await _delay(300, 700)

            # ── 4. Click view-count option ────────────────────────
            await _cb(f"👆 Selecting {CONFIG.view_count} views…")
            view_selectors = [
                f"text={CONFIG.view_count}",
                f"[data-value='{CONFIG.view_count}']",
                f"label:has-text('{CONFIG.view_count}')",
                f"input[value='{CONFIG.view_count}']",
                f".quantity-option:has-text('{CONFIG.view_count}')",
                f"button:has-text('{CONFIG.view_count}')",
                f"[class*='option']:has-text('{CONFIG.view_count}')",
            ]
            clicked = await _try_selectors(page, view_selectors)
            if clicked:
                await clicked.click()
            # Non-fatal: some sites auto-select 200

            await _delay()

            # ── 5. Fill URL field ─────────────────────────────────
            await _cb("🔗 Entering TikTok URL…")
            url_selectors = [
                "input[type='url']",
                "input[placeholder*='tiktok' i]",
                "input[placeholder*='TikTok' i]",
                "input[placeholder*='link' i]",
                "input[placeholder*='video' i]",
                "input[name='url']",
                "input[name='link']",
                "input[name='video']",
                ".url-input",
                "#url",
                "#link",
                "input[type='text']",
            ]
            inp = await _try_selectors(page, url_selectors)
            if not inp:
                html_snippet = (await page.content())[:800]
                return {
                    "success": False,
                    "message": f"❌ URL input not found. DOM: {html_snippet[:200]}",
                    "proxy": proxy_url,
                    "duration": time.time() - t_start,
                }

            await inp.click()
            await inp.fill("")
            await inp.press_sequentially(
                tiktok_url,
                delay=random.randint(30, 80),   # fast typing
            )
            await _delay()

            # ── 6. Submit ─────────────────────────────────────────
            await _cb("📤 Submitting request…")
            submit_selectors = [
                "button[type='submit']",
                "button:has-text('Send')",
                "button:has-text('Get')",
                "button:has-text('Free')",
                "button:has-text('Start')",
                "button:has-text('Submit')",
                "button:has-text('Order')",
                "input[type='submit']",
                ".submit-btn",
                "#submit",
                "[class*='submit']",
                "[class*='btn-primary']",
            ]
            btn = await _try_selectors(page, submit_selectors, timeout_each=3500)
            if btn:
                await btn.click()
            else:
                await page.keyboard.press("Enter")

            # ── 7. Wait for confirmation ──────────────────────────
            wait_s = random.uniform(
                CONFIG.submit_wait_min / 1000,
                CONFIG.submit_wait_max / 1000,
            )
            await _cb(f"⏳ Waiting for response… (~{wait_s:.1f}s)")
            await asyncio.sleep(wait_s)

            # ── 8. Parse result ───────────────────────────────────
            page_text  = await page.inner_text("body")
            page_lower = page_text.lower()

            success_signals = [
                "success", "sent", "delivered", "processing",
                "order", "thank", "submitted", "completed",
                "added", "started", "views will",
            ]
            error_signals = [
                "error", "invalid", "failed", "wrong",
                "limit", "exceeded", "try again", "captcha",
                "blocked", "banned",
            ]

            is_success = any(s in page_lower for s in success_signals)
            is_error   = any(s in page_lower for s in error_signals)

            duration = time.time() - t_start

            if is_error and not is_success:
                # Extract relevant error snippet from page
                lines = [l.strip() for l in page_text.splitlines() if l.strip()]
                err_line = next(
                    (l for l in lines if any(e in l.lower() for e in error_signals)),
                    "Site returned error."
                )
                return {
                    "success": False,
                    "message": f"❌ {err_line[:120]}",
                    "proxy": proxy_url,
                    "duration": duration,
                }

            return {
                "success": True,
                "message": f"✅ Views sent! ({duration:.1f}s) via {proxy_url[-25:]}",
                "proxy": proxy_url,
                "duration": duration,
            }

        except asyncio.TimeoutError:
            return {
                "success": False,
                "message": f"❌ Timeout ({CONFIG.page_timeout // 1000}s exceeded) — proxy too slow: {proxy_url[-30:]}",
                "proxy": proxy_url,
                "duration": time.time() - t_start,
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"❌ {type(e).__name__}: {str(e)[:150]}",
                "proxy": proxy_url,
                "duration": time.time() - t_start,
            }
        finally:
            try:
                await context.close()
                await browser.close()
            except Exception:
                pass
