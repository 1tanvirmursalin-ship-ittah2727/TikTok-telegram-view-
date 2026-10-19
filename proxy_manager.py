# proxy_manager.py -- Parallel proxy fetcher + alive checker
# Key upgrade: batch-checks 40 proxies simultaneously → find alive proxy in ~3s instead of 30s.

import asyncio
import aiohttp
import random
import time
from typing import Optional

# ── Import config (lazy to avoid circular at startup) ────────────
def _cfg():
    from config import CONFIG
    return CONFIG


PROXY_SOURCES = [
    "https://www.proxy-list.download/api/v1/get?type=http",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
    "https://raw.githubusercontent.com/RX4096/proxy-list/main/online/http.txt",
]

CHECK_URLS = [
    "http://httpbin.org/ip",
    "http://ipinfo.io/ip",
    "http://icanhazip.com",
]

# ── Pool state ───────────────────────────────────────────────────
_proxy_pool:    list[str] = []
_used_proxies:  set[str]  = set()
_verified_pool: list[str] = []   # pre-verified alive proxies

# ── Stats ────────────────────────────────────────────────────────
proxy_stats = {
    "fetched":   0,
    "checked":   0,
    "alive":     0,
    "dead":      0,
    "used":      0,
    "last_fetch": 0.0,
}

_pool_lock = asyncio.Lock()


# ── Fetch raw proxy list from all sources ────────────────────────
async def fetch_proxies() -> list[str]:
    """Pull proxies from all sources concurrently; deduplicate."""
    proxies: set[str] = set()

    async def pull(session: aiohttp.ClientSession, url: str):
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=8)
            ) as r:
                if r.status == 200:
                    text = await r.text()
                    for line in text.strip().splitlines():
                        line = line.strip()
                        if ":" in line and 10 < len(line) < 32:
                            proxies.add(f"http://{line}")
        except Exception:
            pass

    async with aiohttp.ClientSession() as session:
        await asyncio.gather(*[pull(session, u) for u in PROXY_SOURCES])

    proxy_stats["fetched"] = len(proxies)
    proxy_stats["last_fetch"] = time.time()
    print(f"[proxy] Fetched {len(proxies)} raw proxies from {len(PROXY_SOURCES)} sources.")
    return list(proxies)


# ── Single alive check ────────────────────────────────────────────
async def _check_one(
    session: aiohttp.ClientSession,
    proxy: str,
    timeout: int,
) -> bool:
    check_url = random.choice(CHECK_URLS)
    try:
        async with session.get(
            check_url,
            proxy=proxy,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as r:
            proxy_stats["checked"] += 1
            if r.status == 200:
                proxy_stats["alive"] += 1
                return True
            proxy_stats["dead"] += 1
            return False
    except Exception:
        proxy_stats["dead"] += 1
        return False


# ── Parallel batch alive-check ────────────────────────────────────
async def batch_check_proxies(candidates: list[str], batch: int, timeout: int) -> list[str]:
    """
    Check `candidates` in parallel batches of `batch` size.
    Returns list of alive proxies.
    """
    alive: list[str] = []
    sem = asyncio.Semaphore(batch)

    async def worker(session: aiohttp.ClientSession, proxy: str):
        async with sem:
            ok = await _check_one(session, proxy, timeout)
            if ok:
                alive.append(proxy)

    async with aiohttp.ClientSession() as session:
        await asyncio.gather(*[worker(session, p) for p in candidates])

    return alive


# ── Pre-warm: fetch + verify N proxies at startup ─────────────────
async def prewarm_pool(count: int = 60) -> int:
    """
    Called once at bot startup. Fills _verified_pool with `count` alive proxies.
    Returns number of verified proxies.
    """
    global _verified_pool, _proxy_pool
    cfg = _cfg()

    print(f"[proxy] Pre-warming pool (target: {count} alive proxies)...")
    raw = await fetch_proxies()
    random.shuffle(raw)

    # Filter previously used
    candidates = [p for p in raw if p not in _used_proxies]

    # Batch check until we have enough
    alive: list[str] = []
    cursor = 0
    while len(alive) < count and cursor < len(candidates):
        chunk = candidates[cursor: cursor + cfg.proxy_batch * 4]
        cursor += len(chunk)
        found = await batch_check_proxies(chunk, cfg.proxy_batch, cfg.proxy_timeout)
        alive.extend(found)
        print(f"[proxy] Pre-warm: {len(alive)}/{count} alive so far…")

    async with _pool_lock:
        _verified_pool = alive[:count]
        _proxy_pool = candidates[cursor:]  # remaining raw for later

    print(f"[proxy] Pool warm: {len(_verified_pool)} verified alive proxies ready.")
    return len(_verified_pool)


# ── Get one fresh alive proxy ─────────────────────────────────────
async def get_fresh_proxy() -> Optional[str]:
    """
    Pop one verified proxy from the pool.
    If verified pool is low, refill from raw pool or re-fetch.
    """
    global _verified_pool, _proxy_pool, _used_proxies
    cfg = _cfg()

    async with _pool_lock:
        # Try verified pool first (already alive-checked)
        while _verified_pool:
            p = _verified_pool.pop(0)
            if p not in _used_proxies:
                _used_proxies.add(p)
                proxy_stats["used"] += 1
                print(f"[proxy] ✅ Using verified: {p}")
                return p

    # Verified pool empty → batch-check from raw pool
    print("[proxy] Verified pool empty; running batch check…")

    async with _pool_lock:
        if len(_proxy_pool) < cfg.proxy_batch:
            fresh = await fetch_proxies()
            _proxy_pool.extend([p for p in fresh if p not in _used_proxies])
            random.shuffle(_proxy_pool)

        chunk = _proxy_pool[:cfg.proxy_batch * 2]
        _proxy_pool = _proxy_pool[cfg.proxy_batch * 2:]

    alive = await batch_check_proxies(chunk, cfg.proxy_batch, cfg.proxy_timeout)

    if not alive:
        # Last resort: reset used set and retry
        async with _pool_lock:
            print("[proxy] Pool exhausted; resetting used set.")
            _used_proxies.clear()
            raw = await fetch_proxies()
            random.shuffle(raw)
            alive = await batch_check_proxies(raw[:80], cfg.proxy_batch, cfg.proxy_timeout)

    if alive:
        candidate = alive[0]
        async with _pool_lock:
            _verified_pool = alive[1:]   # stash rest for next calls
            _used_proxies.add(candidate)
            proxy_stats["used"] += 1
        print(f"[proxy] ✅ Using: {candidate}")
        return candidate

    return None


# ── Stats string ──────────────────────────────────────────────────
def proxy_stats_html() -> str:
    last = proxy_stats["last_fetch"]
    ago  = f"{int(time.time() - last)}s ago" if last else "never"
    return (
        f"<b>🌐 PROXY STATS</b>\n"
        f"├ 📥 Fetched:   <code>{proxy_stats['fetched']}</code>\n"
        f"├ 🔍 Checked:   <code>{proxy_stats['checked']}</code>\n"
        f"├ ✅ Alive:     <code>{proxy_stats['alive']}</code>\n"
        f"├ ❌ Dead:      <code>{proxy_stats['dead']}</code>\n"
        f"├ 🚀 Used:      <code>{proxy_stats['used']}</code>\n"
        f"├ 🏊 Pool left: <code>{len(_verified_pool)}</code>\n"
        f"└ 🕐 Last fetch:<code>{ago}</code>"
    )
