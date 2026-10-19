# config.py -- Central settings & speed presets
# All tunable parameters. Edit here or via /panel in Telegram.

import json
import os
from dataclasses import dataclass, asdict

CONFIG_FILE = "panel_config.json"


@dataclass
class BotConfig:
    # ── Speed / Delay ────────────────────────────────────────────
    min_delay_ms: int   = 200      # human-like delay floor (ms)
    max_delay_ms: int   = 600      # human-like delay ceiling (ms)
    loop_delay_min: float = 7.0    # pause between loop runs (s)
    loop_delay_max: float = 12.0   # pause between loop runs (s)

    # ── Workers ──────────────────────────────────────────────────
    max_workers: int    = 3        # concurrent view-send tasks

    # ── Proxy ────────────────────────────────────────────────────
    proxy_batch:   int  = 40       # parallel alive-check count
    proxy_timeout: int  = 3        # alive-check timeout (s)
    proxy_preload: int  = 60       # proxies to verify at startup

    # ── Browser ──────────────────────────────────────────────────
    page_timeout:  int  = 28000    # page.goto timeout (ms)
    submit_wait_min: int = 3000    # wait after submit – min (ms)
    submit_wait_max: int = 5500    # wait after submit – max (ms)

    # ── View ─────────────────────────────────────────────────────
    view_count: str     = "200"    # quantity option to click

    # ── Meta ─────────────────────────────────────────────────────
    speed_mode: str     = "fast"   # slow | normal | fast | ultra
    bot_token:  str     = "8818515366:AAGmHatlqmuGEwhzRoGV3H27HjMhNZlqHP4"

    # ─────────────────────────────────────────────────────────────
    PRESETS: dict = None           # populated after __post_init__

    def __post_init__(self):
        self.PRESETS = {
            "slow": dict(
                min_delay_ms=1500, max_delay_ms=3000,
                loop_delay_min=25, loop_delay_max=40,
                max_workers=1, submit_wait_min=6000, submit_wait_max=10000,
            ),
            "normal": dict(
                min_delay_ms=700,  max_delay_ms=1800,
                loop_delay_min=12, loop_delay_max=20,
                max_workers=2, submit_wait_min=4500, submit_wait_max=7000,
            ),
            "fast": dict(
                min_delay_ms=200,  max_delay_ms=600,
                loop_delay_min=7,  loop_delay_max=12,
                max_workers=3, submit_wait_min=3000, submit_wait_max=5500,
            ),
            "ultra": dict(
                min_delay_ms=80,   max_delay_ms=280,
                loop_delay_min=4,  loop_delay_max=8,
                max_workers=5, submit_wait_min=2500, submit_wait_max=4000,
            ),
        }

    def apply_preset(self, mode: str) -> None:
        """Apply a named speed preset, preserve bot_token."""
        token = self.bot_token
        preset = self.PRESETS.get(mode)
        if preset:
            for k, v in preset.items():
                setattr(self, k, v)
        self.speed_mode = mode
        self.bot_token = token

    def speed_label(self) -> str:
        icons = {"slow": "🐢", "normal": "🚶", "fast": "🏃", "ultra": "⚡"}
        return f"{icons.get(self.speed_mode, '❓')} {self.speed_mode.upper()}"

    def save(self) -> None:
        data = {k: v for k, v in asdict(self).items() if k != "PRESETS"}
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls) -> "BotConfig":
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE) as f:
                    data = json.load(f)
                cfg = cls()
                for k, v in data.items():
                    if hasattr(cfg, k) and k != "PRESETS":
                        setattr(cfg, k, v)
                return cfg
            except Exception:
                pass
        return cls()


# ── Singleton ────────────────────────────────────────────────────
CONFIG = BotConfig.load()
CONFIG.apply_preset(CONFIG.speed_mode)
