# bot.py -- Ultra Premium Dashboard · PTB v21 · async
# Features: live stats, control panel, speed presets, worker control,
#            real-time ETA, error log, proxy stats, concurrent loop workers.

import asyncio
import logging
import random
import time
from typing import Optional

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, ConversationHandler, filters,
)
from telegram.error import BadRequest
from telegram.constants import ParseMode

from config  import CONFIG
from stats   import STATS
from automation import send_views
import proxy_manager as PM

# ── Logging ───────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("dashboard")

# ── Conversation states ───────────────────────────────────────────
WAITING_URL   = 1
WAITING_COUNT = 2
WAITING_CUSTOM = 3   # generic text input for custom values

# ── Active loop tracker ───────────────────────────────────────────
_active_loops: dict[int, asyncio.Task]  = {}
_loop_sem:     asyncio.Semaphore | None = None

def _get_sem() -> asyncio.Semaphore:
    global _loop_sem
    if _loop_sem is None or _loop_sem._value != CONFIG.max_workers:
        _loop_sem = asyncio.Semaphore(CONFIG.max_workers)
    return _loop_sem


# ══════════════════════════════════════════════════════════════════
#  DASHBOARD BUILDERS
# ══════════════════════════════════════════════════════════════════

def _main_menu_text() -> str:
    pool_size = len(PM._verified_pool)
    return (
        "╔═══════════════════════════════╗\n"
        "║  🦅  <b>LEOFAME VIEW BOMBER</b>      ║\n"
        "║      <b>ULTRA DASHBOARD v4.0</b>      ║\n"
        "╚═══════════════════════════════╝\n\n"
        + STATS.dashboard_html()
        + f"\n\n<b>⚙️ CURRENT SETTINGS</b>\n"
        f"├ {CONFIG.speed_label()}  speed mode\n"
        f"├ 👷 <b>Workers</b>  <code>{CONFIG.max_workers}</code>\n"
        f"├ 🌐 <b>Proxy pool</b>  <code>{pool_size}</code> alive\n"
        f"└ ⏱ <b>Loop delay</b>  <code>{CONFIG.loop_delay_min:.0f}–{CONFIG.loop_delay_max:.0f}s</code>"
    )

def _main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 Send Views",   callback_data="send"),
            InlineKeyboardButton("🔁 Loop Mode",    callback_data="loop"),
        ],
        [
            InlineKeyboardButton("⚙️ Control Panel", callback_data="panel"),
            InlineKeyboardButton("📊 Stats",         callback_data="stats"),
        ],
        [
            InlineKeyboardButton("🌐 Proxy Stats",   callback_data="proxy_stats"),
            InlineKeyboardButton("⚠️ Error Log",      callback_data="errors"),
        ],
        [
            InlineKeyboardButton("⛔ Stop Loop",     callback_data="stop"),
            InlineKeyboardButton("🔄 Refresh Menu",  callback_data="refresh_menu"),
        ],
    ])


def _panel_text() -> str:
    d_lo = CONFIG.min_delay_ms
    d_hi = CONFIG.max_delay_ms
    l_lo = CONFIG.loop_delay_min
    l_hi = CONFIG.loop_delay_max
    return (
        "⚙️ <b>CONTROL PANEL</b>\n\n"
        f"<b>🏃 Speed Mode</b>  →  {CONFIG.speed_label()}\n"
        f"<b>👷 Workers</b>     →  <code>{CONFIG.max_workers}</code> concurrent\n"
        f"<b>⏱ Human delay</b> →  <code>{d_lo}–{d_hi} ms</code>\n"
        f"<b>🔁 Loop delay</b>  →  <code>{l_lo:.0f}–{l_hi:.0f} s</code>\n"
        f"<b>🌐 Proxy batch</b> →  <code>{CONFIG.proxy_batch}</code> parallel checks\n"
        f"<b>👁 View count</b>  →  <code>{CONFIG.view_count}</code>\n\n"
        "Select what to change 👇"
    )

def _panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🐢 SLOW",   callback_data="sp_slow"),
            InlineKeyboardButton("🚶 NORMAL",  callback_data="sp_normal"),
            InlineKeyboardButton("🏃 FAST",   callback_data="sp_fast"),
            InlineKeyboardButton("⚡ ULTRA",  callback_data="sp_ultra"),
        ],
        [
            InlineKeyboardButton("👷 Workers ➖", callback_data="wk_dec"),
            InlineKeyboardButton(f"  {CONFIG.max_workers}  ",  callback_data="wk_noop"),
            InlineKeyboardButton("👷 Workers ➕", callback_data="wk_inc"),
        ],
        [
            InlineKeyboardButton("⏱ Delay ➖", callback_data="dl_dec"),
            InlineKeyboardButton(f"  {CONFIG.min_delay_ms}–{CONFIG.max_delay_ms}ms  ", callback_data="dl_noop"),
            InlineKeyboardButton("⏱ Delay ➕", callback_data="dl_inc"),
        ],
        [
            InlineKeyboardButton("🔁 Loop ➖", callback_data="ld_dec"),
            InlineKeyboardButton(f"  {CONFIG.loop_delay_min:.0f}–{CONFIG.loop_delay_max:.0f}s  ", callback_data="ld_noop"),
            InlineKeyboardButton("🔁 Loop ➕", callback_data="ld_inc"),
        ],
        [
            InlineKeyboardButton("🌐 Refresh Proxy Pool", callback_data="proxy_refresh"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Menu", callback_data="refresh_menu"),
        ],
    ])


def _stats_text() -> str:
    errs = STATS.last_errors()
    err_block = ""
    if errs:
        err_block = "\n\n<b>⚠️ Recent Errors</b>\n" + "\n".join(
            f"<code>{e[:80]}</code>" for e in errs[-4:]
        )
    return (
        "📊 <b>FULL STATISTICS</b>\n\n"
        + STATS.dashboard_html()
        + err_block
    )


def _proxy_text() -> str:
    return PM.proxy_stats_html()


def _error_log_text() -> str:
    errs = STATS.last_errors()
    if not errs:
        return "✅ <b>No errors recorded yet.</b>"
    lines = "\n\n".join(
        f"<b>{i+1}.</b> <code>{e}</code>" for i, e in enumerate(errs)
    )
    return f"⚠️ <b>ERROR LOG</b> (last {len(errs)})\n\n{lines}"


# ══════════════════════════════════════════════════════════════════
#  HELPER: safe message edit
# ══════════════════════════════════════════════════════════════════

async def _safe_edit(msg: Message, text: str, reply_markup=None, parse_mode=ParseMode.HTML):
    try:
        kwargs = dict(text=text, parse_mode=parse_mode)
        if reply_markup:
            kwargs["reply_markup"] = reply_markup
        await msg.edit_text(**kwargs)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            log.warning(f"edit_text failed: {e}")
    except Exception as e:
        log.warning(f"edit_text error: {e}")


# ══════════════════════════════════════════════════════════════════
#  COMMAND HANDLERS
# ══════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        _main_menu_text(),
        reply_markup=_main_menu_kb(),
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if chat_id in _active_loops:
        _active_loops[chat_id].cancel()
        del _active_loops[chat_id]
        await update.message.reply_text("⛔ <b>Loop stopped.</b>", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text("ℹ️ No active loop.", parse_mode=ParseMode.HTML)
    return ConversationHandler.END


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(_stats_text(), parse_mode=ParseMode.HTML)


async def cmd_errors(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(_error_log_text(), parse_mode=ParseMode.HTML)


async def cmd_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        _panel_text(),
        reply_markup=_panel_kb(),
        parse_mode=ParseMode.HTML,
    )


# ══════════════════════════════════════════════════════════════════
#  CALLBACK QUERY HANDLER (button presses)
# ══════════════════════════════════════════════════════════════════

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q       = update.callback_query
    data    = q.data
    chat_id = q.message.chat_id
    await q.answer()

    # ── Main menu / navigation ────────────────────────────────────
    if data == "refresh_menu":
        await _safe_edit(q.message, _main_menu_text(), _main_menu_kb())
        return ConversationHandler.END

    if data == "stats":
        await _safe_edit(q.message, _stats_text())
        return ConversationHandler.END

    if data == "proxy_stats":
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Refresh Proxies", callback_data="proxy_refresh"),
            InlineKeyboardButton("🔙 Menu",            callback_data="refresh_menu"),
        ]])
        await _safe_edit(q.message, _proxy_text(), kb)
        return ConversationHandler.END

    if data == "errors":
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Menu", callback_data="refresh_menu"),
        ]])
        await _safe_edit(q.message, _error_log_text(), kb)
        return ConversationHandler.END

    if data == "panel":
        await _safe_edit(q.message, _panel_text(), _panel_kb())
        return ConversationHandler.END

    # ── Speed presets ─────────────────────────────────────────────
    if data in ("sp_slow", "sp_normal", "sp_fast", "sp_ultra"):
        mode = data[3:]   # strip "sp_"
        CONFIG.apply_preset(mode)
        CONFIG.save()
        global _loop_sem
        _loop_sem = asyncio.Semaphore(CONFIG.max_workers)
        await _safe_edit(
            q.message,
            f"✅ Speed set to <b>{CONFIG.speed_label()}</b>",
        )
        await asyncio.sleep(1.0)
        await _safe_edit(q.message, _panel_text(), _panel_kb())
        return ConversationHandler.END

    # ── Worker adjustment ─────────────────────────────────────────
    if data == "wk_dec":
        CONFIG.max_workers = max(1, CONFIG.max_workers - 1)
        CONFIG.save()
        _loop_sem = asyncio.Semaphore(CONFIG.max_workers)
        await _safe_edit(q.message, _panel_text(), _panel_kb())
        return ConversationHandler.END

    if data == "wk_inc":
        CONFIG.max_workers = min(10, CONFIG.max_workers + 1)
        CONFIG.save()
        _loop_sem = asyncio.Semaphore(CONFIG.max_workers)
        await _safe_edit(q.message, _panel_text(), _panel_kb())
        return ConversationHandler.END

    # ── Human delay adjustment ────────────────────────────────────
    if data == "dl_dec":
        CONFIG.min_delay_ms = max(50,   CONFIG.min_delay_ms - 100)
        CONFIG.max_delay_ms = max(150,  CONFIG.max_delay_ms - 200)
        CONFIG.save()
        await _safe_edit(q.message, _panel_text(), _panel_kb())
        return ConversationHandler.END

    if data == "dl_inc":
        CONFIG.min_delay_ms = min(3000, CONFIG.min_delay_ms + 100)
        CONFIG.max_delay_ms = min(6000, CONFIG.max_delay_ms + 200)
        CONFIG.save()
        await _safe_edit(q.message, _panel_text(), _panel_kb())
        return ConversationHandler.END

    # ── Loop delay adjustment ─────────────────────────────────────
    if data == "ld_dec":
        CONFIG.loop_delay_min = max(2.0, CONFIG.loop_delay_min - 2)
        CONFIG.loop_delay_max = max(4.0, CONFIG.loop_delay_max - 3)
        CONFIG.save()
        await _safe_edit(q.message, _panel_text(), _panel_kb())
        return ConversationHandler.END

    if data == "ld_inc":
        CONFIG.loop_delay_min = min(120, CONFIG.loop_delay_min + 2)
        CONFIG.loop_delay_max = min(180, CONFIG.loop_delay_max + 3)
        CONFIG.save()
        await _safe_edit(q.message, _panel_text(), _panel_kb())
        return ConversationHandler.END

    # ── Noop buttons (display labels) ────────────────────────────
    if data in ("wk_noop", "dl_noop", "ld_noop"):
        return ConversationHandler.END

    # ── Proxy refresh ─────────────────────────────────────────────
    if data == "proxy_refresh":
        await _safe_edit(q.message, "🌐 <b>Refreshing proxy pool… please wait.</b>")
        count = await PM.prewarm_pool(CONFIG.proxy_preload)
        await _safe_edit(
            q.message,
            f"✅ <b>Proxy pool refreshed!</b> <code>{count}</code> alive proxies loaded.",
        )
        await asyncio.sleep(1.5)
        await _safe_edit(q.message, _panel_text(), _panel_kb())
        return ConversationHandler.END

    # ── Send / Loop entry points ──────────────────────────────────
    if data == "send":
        ctx.user_data["mode"] = "single"
        await q.message.reply_text(
            "🔗 <b>Enter TikTok video URL:</b>",
            parse_mode=ParseMode.HTML,
        )
        return WAITING_URL

    if data == "loop":
        ctx.user_data["mode"] = "loop"
        await q.message.reply_text(
            "🔢 <b>How many times to loop?</b>\n"
            "<code>0</code> = infinite loop\n"
            "Enter a number:",
            parse_mode=ParseMode.HTML,
        )
        return WAITING_COUNT

    # ── Stop ─────────────────────────────────────────────────────
    if data == "stop":
        if chat_id in _active_loops:
            _active_loops[chat_id].cancel()
            del _active_loops[chat_id]
            await _safe_edit(q.message, "⛔ <b>Loop stopped.</b>")
        else:
            await _safe_edit(q.message, "ℹ️ No active loop running.")
        return ConversationHandler.END

    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════
#  CONVERSATION STATE HANDLERS
# ══════════════════════════════════════════════════════════════════

async def state_get_count(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    try:
        n = int(txt)
        ctx.user_data["loop_count"] = n if n > 0 else float("inf")
    except ValueError:
        await update.message.reply_text("❌ Please enter a number.")
        return WAITING_COUNT

    await update.message.reply_text(
        "🔗 <b>Enter TikTok video URL:</b>",
        parse_mode=ParseMode.HTML,
    )
    return WAITING_URL


async def state_get_url(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    url     = update.message.text.strip()
    chat_id = update.message.chat_id

    if "tiktok.com" not in url.lower():
        await update.message.reply_text("❌ <b>Invalid URL.</b> Must contain tiktok.com", parse_mode=ParseMode.HTML)
        return WAITING_URL

    mode  = ctx.user_data.get("mode", "single")
    count = ctx.user_data.get("loop_count", 1)

    if mode == "single":
        asyncio.create_task(_run_single(update.message, url))
    else:
        count_label = "∞" if count == float("inf") else str(int(count))
        await update.message.reply_text(
            f"🔁 <b>Loop started:</b> <code>{count_label}</code> runs\n"
            f"⚡ Speed: {CONFIG.speed_label()} | 👷 Workers: <code>{CONFIG.max_workers}</code>\n"
            f"⛔ /stop to cancel",
            parse_mode=ParseMode.HTML,
        )
        task = asyncio.create_task(_run_loop(update.message, url, count))
        _active_loops[chat_id] = task

    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════
#  SINGLE RUN
# ══════════════════════════════════════════════════════════════════

async def _run_single(msg: Message, url: str):
    status_msg = await msg.reply_text(
        "⚙️ <b>Initializing…</b>",
        parse_mode=ParseMode.HTML,
    )
    t_start = time.time()

    async def progress(text: str):
        elapsed = time.time() - t_start
        await _safe_edit(
            status_msg,
            f"⚙️ <b>RUNNING</b> ({elapsed:.1f}s)\n\n{text}",
        )

    result   = await send_views(url, progress_callback=progress)
    duration = result.get("duration", time.time() - t_start)
    await STATS.record(result, duration)

    icon    = "✅" if result["success"] else "❌"
    proxy   = result.get("proxy") or "N/A"
    message = result.get("message", "")

    await _safe_edit(
        status_msg,
        f"{icon} <b>{'DONE' if result['success'] else 'FAILED'}</b>  |  "
        f"<code>{duration:.1f}s</code>\n\n"
        f"{message}\n\n"
        f"🌐 <code>{proxy}</code>\n\n"
        + STATS.dashboard_html(),
        InlineKeyboardMarkup([[
            InlineKeyboardButton("🔁 Send Again",    callback_data="send"),
            InlineKeyboardButton("📊 Full Stats",    callback_data="stats"),
            InlineKeyboardButton("🏠 Menu",          callback_data="refresh_menu"),
        ]]),
    )


# ══════════════════════════════════════════════════════════════════
#  LOOP RUN  (concurrent workers via semaphore)
# ══════════════════════════════════════════════════════════════════

async def _run_loop(msg: Message, url: str, total_count):
    """
    Runs up to CONFIG.max_workers concurrent view-sends at once.
    Posts a live progress card per run, plus a summary card after each batch.
    """
    sem  = _get_sem()
    sent = 0
    t_loop_start = time.time()

    # ── summary card pinned at top ────────────────────────────────
    summary_msg = await msg.reply_text(
        "📋 <b>LOOP STARTED</b>\n\nInitializing workers…",
        parse_mode=ParseMode.HTML,
    )

    async def _one_run(run_idx: int):
        nonlocal sent
        async with sem:
            run_msg = await msg.reply_text(
                f"▶️ <b>Run #{run_idx}</b>  starting…",
                parse_mode=ParseMode.HTML,
            )
            t0 = time.time()

            async def progress(text: str):
                elapsed = time.time() - t0
                eta     = STATS.eta_for(
                    max(0, (int(total_count) if total_count != float("inf") else 0) - sent)
                )
                await _safe_edit(
                    run_msg,
                    f"▶️ <b>Run #{run_idx}</b>  ({elapsed:.1f}s)\n"
                    f"{text}\n"
                    f"📉 ETA: <code>{eta}</code>"
                )

            result   = await send_views(url, progress_callback=progress)
            duration = result.get("duration", time.time() - t0)
            await STATS.record(result, duration)
            sent += 1

            icon = "✅" if result["success"] else "❌"
            await _safe_edit(
                run_msg,
                f"{icon} <b>Run #{run_idx}</b>  <code>{duration:.1f}s</code>\n"
                f"{result['message']}\n"
                f"🌐 <code>{result.get('proxy', 'N/A')}</code>"
            )

    try:
        if total_count == float("inf"):
            # Infinite loop — batch scheduling
            run_idx = 1
            while True:
                # Launch max_workers tasks concurrently
                batch = [asyncio.create_task(_one_run(run_idx + i))
                         for i in range(CONFIG.max_workers)]
                await asyncio.gather(*batch)
                run_idx += CONFIG.max_workers

                # Update summary after each batch
                elapsed = time.time() - t_loop_start
                await _safe_edit(
                    summary_msg,
                    f"🔁 <b>LOOP RUNNING</b> ∞\n\n"
                    f"📤 Sent:   <code>{sent}</code>\n"
                    f"✅ OK:     <code>{STATS.total_success}</code>\n"
                    f"❌ Fail:   <code>{STATS.total_failed}</code>\n"
                    f"⏱ Elapsed: <code>{int(elapsed)}s</code>\n"
                    f"⚡ Speed:  {CONFIG.speed_label()}\n\n"
                    "/stop to cancel",
                )
                await asyncio.sleep(random.uniform(CONFIG.loop_delay_min, CONFIG.loop_delay_max))

        else:
            total = int(total_count)
            run_idx = 1
            while sent < total:
                batch_size = min(CONFIG.max_workers, total - sent)
                batch = [asyncio.create_task(_one_run(run_idx + i))
                         for i in range(batch_size)]
                await asyncio.gather(*batch)
                run_idx += batch_size

                remaining = total - sent
                eta = STATS.eta_for(remaining)
                bar = STATS.progress_bar(sent, total)
                pct = sent / total * 100

                await _safe_edit(
                    summary_msg,
                    f"🔁 <b>LOOP PROGRESS</b>\n\n"
                    f"<code>[{bar}]</code> <code>{pct:.0f}%</code>\n\n"
                    f"📤 Done:      <code>{sent}/{total}</code>\n"
                    f"✅ Success:   <code>{STATS.total_success}</code>\n"
                    f"❌ Failed:    <code>{STATS.total_failed}</code>\n"
                    f"📈 Rate:      <code>{STATS.success_rate():.1f}%</code>\n"
                    f"⚡ Avg/run:   <code>{STATS.avg_duration():.1f}s</code>\n"
                    f"⏳ ETA:       <code>{eta}</code>\n"
                    f"⚙️ Speed:     {CONFIG.speed_label()}\n\n"
                    "/stop to cancel",
                )

                if sent < total:
                    await asyncio.sleep(random.uniform(CONFIG.loop_delay_min, CONFIG.loop_delay_max))

            # ── Final summary ──────────────────────────────────────
            elapsed = time.time() - t_loop_start
            await _safe_edit(
                summary_msg,
                f"🏁 <b>LOOP COMPLETE</b>\n\n"
                f"📤 Total runs:   <code>{sent}</code>\n"
                f"✅ Success:      <code>{STATS.total_success}</code>\n"
                f"❌ Failed:       <code>{STATS.total_failed}</code>\n"
                f"📈 Success rate: <code>{STATS.success_rate():.1f}%</code>\n"
                f"⚡ Avg/run:      <code>{STATS.avg_duration():.1f}s</code>\n"
                f"⏱ Total time:   <code>{int(elapsed)}s</code>",
                InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔁 New Loop", callback_data="loop"),
                    InlineKeyboardButton("🏠 Menu",     callback_data="refresh_menu"),
                ]]),
            )

    except asyncio.CancelledError:
        await _safe_edit(
            summary_msg,
            f"⛔ <b>LOOP CANCELLED</b>\n\n"
            f"📤 Completed: <code>{sent}</code> runs\n"
            f"✅ Success:   <code>{STATS.total_success}</code>\n"
            f"❌ Failed:    <code>{STATS.total_failed}</code>",
        )
    except Exception as e:
        log.exception(f"Loop error: {e}")
        await _safe_edit(
            summary_msg,
            f"💥 <b>LOOP ERROR</b>\n\n<code>{type(e).__name__}: {str(e)[:200]}</code>",
        )
    finally:
        chat_id = summary_msg.chat_id
        if chat_id in _active_loops:
            del _active_loops[chat_id]


# ══════════════════════════════════════════════════════════════════
#  BOT STARTUP
# ══════════════════════════════════════════════════════════════════

async def _on_startup(app: Application):
    """Pre-warm proxy pool when bot starts."""
    log.info("[startup] Pre-warming proxy pool…")
    try:
        count = await PM.prewarm_pool(CONFIG.proxy_preload)
        log.info(f"[startup] Proxy pool ready: {count} alive proxies.")
    except Exception as e:
        log.warning(f"[startup] Proxy prewarm failed: {e}")


def main():
    app = (
        Application.builder()
        .token(CONFIG.bot_token)
        .build()
    )

    # ── Prewarm via job_queue (fires 3s after polling starts) ────
    async def _startup_prewarm(context: ContextTypes.DEFAULT_TYPE):
        log.info("[startup] Pre-warming proxy pool…")
        try:
            count = await PM.prewarm_pool(CONFIG.proxy_preload)
            log.info(f"[startup] Proxy pool ready: {count} alive proxies.")
        except Exception as e:
            log.warning(f"[startup] Prewarm failed: {e}")

    app.job_queue.run_once(_startup_prewarm, when=3)

    # ── Register handlers ─────────────────────────────────────────
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            CallbackQueryHandler(callback_handler),
        ],
        states={
            WAITING_COUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, state_get_count),
            ],
            WAITING_URL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, state_get_url),
            ],
        },
        fallbacks=[
            CommandHandler("stop",   cmd_stop),
            CommandHandler("stats",  cmd_stats),
            CommandHandler("errors", cmd_errors),
            CommandHandler("panel",  cmd_panel),
        ],
        per_chat=True,
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("stop",   cmd_stop))
    app.add_handler(CommandHandler("stats",  cmd_stats))
    app.add_handler(CommandHandler("errors", cmd_errors))
    app.add_handler(CommandHandler("panel",  cmd_panel))

    log.info("════════════════════════════════════════")
    log.info("  🦅 LEOFAME VIEW BOMBER  ULTRA v4.0   ")
    log.info("════════════════════════════════════════")
    log.info(f"  Speed:   {CONFIG.speed_label()}")
    log.info(f"  Workers: {CONFIG.max_workers}")
    log.info(f"  Delays:  {CONFIG.min_delay_ms}–{CONFIG.max_delay_ms} ms")
    log.info("════════════════════════════════════════")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
