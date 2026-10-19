# stats.py -- Runtime statistics tracker
# Tracks every run result; provides ETA, success rate, error log, dashboard text.

import asyncio
import time
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class RunResult:
    timestamp: float
    success: bool
    proxy: Optional[str]
    message: str
    duration: float          # seconds taken for this run


class StatsTracker:
    def __init__(self):
        self.total_sent:    int  = 0
        self.total_success: int  = 0
        self.total_failed:  int  = 0
        self.session_start: float = time.time()
        self._results:  List[RunResult] = []
        self._errors:   List[str]       = []   # last 8 error messages
        self._lock = asyncio.Lock()

    # ── Record a completed run ───────────────────────────────────
    async def record(self, result: dict, duration: float) -> None:
        async with self._lock:
            self.total_sent += 1
            run = RunResult(
                timestamp=time.time(),
                success=result["success"],
                proxy=result.get("proxy"),
                message=result.get("message", ""),
                duration=duration,
            )
            self._results.append(run)
            if len(self._results) > 100:
                self._results.pop(0)

            if result["success"]:
                self.total_success += 1
            else:
                self.total_failed += 1
                err = result.get("message", "Unknown error")
                self._errors.append(f"[{self._ts()}] {err[:120]}")
                if len(self._errors) > 8:
                    self._errors.pop(0)

    # ── Computed properties ──────────────────────────────────────
    def success_rate(self) -> float:
        return (self.total_success / self.total_sent * 100) if self.total_sent else 0.0

    def avg_duration(self) -> float:
        recent = self._results[-10:]
        return (sum(r.duration for r in recent) / len(recent)) if recent else 0.0

    def runs_per_minute(self) -> float:
        elapsed = time.time() - self.session_start
        return (self.total_sent / elapsed * 60) if elapsed > 0 else 0.0

    def eta_for(self, remaining: int) -> str:
        avg = self.avg_duration()
        if avg == 0:
            return "calculating…"
        secs = avg * remaining
        if secs < 60:
            return f"{int(secs)}s"
        elif secs < 3600:
            return f"{int(secs // 60)}m {int(secs % 60)}s"
        else:
            return f"{int(secs // 3600)}h {int((secs % 3600) // 60)}m"

    def session_uptime(self) -> str:
        secs = int(time.time() - self.session_start)
        if secs < 60:
            return f"{secs}s"
        elif secs < 3600:
            return f"{secs // 60}m {secs % 60}s"
        else:
            return f"{secs // 3600}h {(secs % 3600) // 60}m"

    def last_errors(self) -> List[str]:
        return list(self._errors)

    def progress_bar(self, current: int, total: int, width: int = 12) -> str:
        if total <= 0:
            return "░" * width
        pct = current / total
        filled = int(pct * width)
        return "█" * filled + "░" * (width - filled)

    def rate_bar(self, width: int = 10) -> str:
        rate = self.success_rate()
        filled = int(rate / 100 * width)
        return "█" * filled + "░" * (width - filled)

    # ── Dashboard block (HTML-safe) ──────────────────────────────
    def dashboard_html(self) -> str:
        rate = self.success_rate()
        avg  = self.avg_duration()
        rpm  = self.runs_per_minute()
        return (
            f"<b>📊 LIVE STATS</b>\n"
            f"├ ✅ <b>Success</b>  <code>{self.total_success}</code>\n"
            f"├ ❌ <b>Failed</b>   <code>{self.total_failed}</code>\n"
            f"├ 📤 <b>Total</b>    <code>{self.total_sent}</code>\n"
            f"├ 📈 <b>Rate</b>     <code>{rate:.1f}%</code>  <code>[{self.rate_bar()}]</code>\n"
            f"├ ⚡ <b>Avg/run</b>  <code>{avg:.1f}s</code>\n"
            f"├ 🔄 <b>RPM</b>      <code>{rpm:.2f}</code>\n"
            f"└ ⏱ <b>Uptime</b>   <code>{self.session_uptime()}</code>"
        )

    # ── Helpers ──────────────────────────────────────────────────
    @staticmethod
    def _ts() -> str:
        return time.strftime("%H:%M:%S")


# ── Singleton ────────────────────────────────────────────────────
STATS = StatsTracker()
