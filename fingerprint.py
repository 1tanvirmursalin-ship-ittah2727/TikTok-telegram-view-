# fingerprint.py -- Browser fingerprint spoofing payloads
# Expanded: canvas, WebGL, audio context, battery API, plugins, fonts, screen.

import random

# ── Pools ─────────────────────────────────────────────────────────
RESOLUTIONS = [
    (1920, 1080), (1366, 768), (1440, 900), (1536, 864),
    (1280, 720),  (1600, 900), (2560, 1440),(1280, 800),
    (1024, 768),  (1920, 1200),(2560, 1080),(3840, 2160),
    (1680, 1050), (1360, 768), (1280, 1024),(1400, 900),
]

TIMEZONES = [
    "Asia/Dhaka",       "Asia/Kolkata",     "Asia/Karachi",
    "Asia/Jakarta",     "Asia/Bangkok",     "Asia/Singapore",
    "Asia/Kuala_Lumpur","Asia/Tokyo",       "Asia/Seoul",
    "Asia/Dubai",       "Asia/Riyadh",      "Asia/Manila",
    "America/New_York", "America/Chicago",  "America/Los_Angeles",
    "America/Toronto",  "Europe/London",    "Europe/Paris",
    "Europe/Berlin",    "Europe/Moscow",    "Australia/Sydney",
    "Pacific/Auckland",
]

LANGUAGES = [
    "en-US", "en-GB", "en-AU", "bn-BD",
    "hi-IN", "ar-SA", "id-ID", "ms-MY",
    "th-TH", "vi-VN", "ko-KR", "ja-JP",
    "tr-TR", "pt-BR", "es-ES",
]

HARDWARE_CONCURRENCY = [2, 4, 4, 6, 8, 8, 12, 16]
DEVICE_MEMORY        = [2, 4, 4, 8, 8, 16]
COLOR_DEPTHS         = [24, 24, 30, 32]

WEBGL_VENDORS = [
    ("Intel Inc.", "Intel Iris OpenGL Engine"),
    ("Intel Inc.", "Intel(R) HD Graphics 620"),
    ("NVIDIA Corporation", "NVIDIA GeForce GTX 1050 Ti/PCIe/SSE2"),
    ("NVIDIA Corporation", "NVIDIA GeForce RTX 3060/PCIe/SSE2"),
    ("ATI Technologies Inc.", "AMD Radeon RX 5500 XT"),
    ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0)"),
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3070 Direct3D11 vs_5_0 ps_5_0)"),
    ("Google Inc. (AMD)",    "ANGLE (AMD, AMD Radeon(TM) Graphics Direct3D11 vs_5_0 ps_5_0)"),
]

PLATFORMS = ["Win32", "Win32", "Win32", "MacIntel", "Linux x86_64"]

PLUGIN_SETS = [
    [
        {"name": "PDF Viewer",           "filename": "internal-pdf-viewer", "description": "Portable Document Format"},
        {"name": "Chrome PDF Viewer",    "filename": "internal-pdf-viewer", "description": "Portable Document Format"},
        {"name": "Chromium PDF Viewer",  "filename": "internal-pdf-viewer", "description": "Portable Document Format"},
        {"name": "Microsoft Edge PDF Viewer","filename":"internal-pdf-viewer","description":"Portable Document Format"},
        {"name": "WebKit built-in PDF",  "filename": "internal-pdf-viewer", "description": "Portable Document Format"},
    ],
    [
        {"name": "PDF Viewer",           "filename": "internal-pdf-viewer", "description": "Portable Document Format"},
        {"name": "Chrome PDF Viewer",    "filename": "internal-pdf-viewer", "description": "Portable Document Format"},
    ],
]


# ── Build fingerprint dict ────────────────────────────────────────
def get_random_fingerprint() -> dict:
    res    = random.choice(RESOLUTIONS)
    vendor, renderer = random.choice(WEBGL_VENDORS)
    return {
        "resolution":          res,
        "timezone":            random.choice(TIMEZONES),
        "language":            random.choice(LANGUAGES),
        "hardware_concurrency":random.choice(HARDWARE_CONCURRENCY),
        "device_memory":       random.choice(DEVICE_MEMORY),
        "color_depth":         random.choice(COLOR_DEPTHS),
        "platform":            random.choice(PLATFORMS),
        "webgl_vendor":        vendor,
        "webgl_renderer":      renderer,
        "plugins":             random.choice(PLUGIN_SETS),
        "do_not_track":        random.choice(["1", "unspecified", None]),
        "battery_charging":    random.choice([True, False]),
        "battery_level":       round(random.uniform(0.35, 1.0), 2),
        "touch_points":        random.choice([0, 0, 0, 1, 5]),
        "max_touch_points":    random.choice([0, 0, 0, 1, 5]),
    }


# ── Build JS injection payload ────────────────────────────────────
def get_fingerprint_js(fp: dict) -> str:
    dnt_val = f"'{fp['do_not_track']}'" if fp["do_not_track"] else "undefined"
    plugins_json = str(fp["plugins"]).replace("'", '"').replace("True","true").replace("False","false").replace("None","null")

    return f"""
(function() {{
    // ── Navigator properties ──────────────────────────────────
    const _def = (obj, prop, val) => {{
        try {{
            Object.defineProperty(obj, prop, {{ get: () => val, configurable: true }});
        }} catch(e) {{}}
    }};

    _def(navigator, 'webdriver',            undefined);
    _def(navigator, 'hardwareConcurrency',  {fp['hardware_concurrency']});
    _def(navigator, 'deviceMemory',         {fp['device_memory']});
    _def(navigator, 'language',             '{fp['language']}');
    _def(navigator, 'languages',            ['{fp['language']}', 'en']);
    _def(navigator, 'platform',             '{fp['platform']}');
    _def(navigator, 'doNotTrack',           {dnt_val});
    _def(navigator, 'maxTouchPoints',       {fp['max_touch_points']});
    _def(navigator, 'cookieEnabled',        true);
    _def(navigator, 'onLine',               true);

    // ── Screen ────────────────────────────────────────────────
    _def(screen, 'width',       {fp['resolution'][0]});
    _def(screen, 'height',      {fp['resolution'][1]});
    _def(screen, 'availWidth',  {fp['resolution'][0]});
    _def(screen, 'availHeight', {fp['resolution'][1] - random.randint(40, 80)});
    _def(screen, 'colorDepth',  {fp['color_depth']});
    _def(screen, 'pixelDepth',  {fp['color_depth']});

    // ── Canvas fingerprint noise ──────────────────────────────
    (function() {{
        const origGetCtx = HTMLCanvasElement.prototype.getContext;
        HTMLCanvasElement.prototype.getContext = function(type, ...args) {{
            const ctx = origGetCtx.call(this, type, ...args);
            if (type === '2d' && ctx) {{
                const orig = ctx.fillText.bind(ctx);
                ctx.fillText = function(...a) {{
                    ctx.shadowColor = '#' + Math.floor(Math.random()*16777215).toString(16).padStart(6,'0');
                    ctx.shadowBlur  = Math.random() * 0.3;
                    return orig(...a);
                }};
                const origStroke = ctx.strokeText.bind(ctx);
                ctx.strokeText = function(...a) {{
                    ctx.shadowColor = '#' + Math.floor(Math.random()*16777215).toString(16).padStart(6,'0');
                    return origStroke(...a);
                }};
            }}
            return ctx;
        }};
    }})();

    // ── WebGL spoof ───────────────────────────────────────────
    (function() {{
        const patchGL = (GLClass) => {{
            if (!window[GLClass]) return;
            const origGetParam = window[GLClass].prototype.getParameter;
            window[GLClass].prototype.getParameter = function(p) {{
                if (p === 37445) return '{fp['webgl_vendor']}';
                if (p === 37446) return '{fp['webgl_renderer']}';
                return origGetParam.call(this, p);
            }};
            const origGetExt = window[GLClass].prototype.getExtension;
            window[GLClass].prototype.getExtension = function(name) {{
                if (name === 'WEBGL_debug_renderer_info') {{
                    return {{ UNMASKED_VENDOR_WEBGL: 37445, UNMASKED_RENDERER_WEBGL: 37446 }};
                }}
                return origGetExt.call(this, name);
            }};
        }};
        patchGL('WebGLRenderingContext');
        patchGL('WebGL2RenderingContext');
    }})();

    // ── Audio context fingerprint noise ───────────────────────
    (function() {{
        const AC = window.AudioContext || window.webkitAudioContext;
        if (!AC) return;
        const origCreateAnalyser = AC.prototype.createAnalyser;
        AC.prototype.createAnalyser = function() {{
            const analyser = origCreateAnalyser.call(this);
            const orig = analyser.getFloatFrequencyData.bind(analyser);
            analyser.getFloatFrequencyData = function(arr) {{
                orig(arr);
                for (let i = 0; i < arr.length; i++) {{
                    arr[i] += (Math.random() - 0.5) * 0.0001;
                }}
            }};
            return analyser;
        }};
    }})();

    // ── Battery API spoof ─────────────────────────────────────
    (function() {{
        const fakeBattery = {{
            charging:        {str(fp['battery_charging']).lower()},
            chargingTime:    {'0' if fp['battery_charging'] else 'Infinity'},
            dischargingTime: {'Infinity' if fp['battery_charging'] else str(random.randint(3600, 18000))},
            level:           {fp['battery_level']},
            addEventListener: () => {{}},
            removeEventListener: () => {{}},
        }};
        if (navigator.getBattery) {{
            navigator.getBattery = () => Promise.resolve(fakeBattery);
        }}
    }})();

    // ── Plugins spoof ─────────────────────────────────────────
    (function() {{
        const pluginData = {plugins_json};
        const makePlugin = (d) => {{ const p = Object.create(Plugin.prototype); Object.assign(p, d); return p; }};
        const fakePlugins = pluginData.map(makePlugin);
        fakePlugins.item   = (i) => fakePlugins[i];
        fakePlugins.namedItem = (n) => fakePlugins.find(p => p.name === n) || null;
        fakePlugins.refresh = () => {{}};
        try {{ _def(navigator, 'plugins', fakePlugins); }} catch(e) {{}}
    }})();

    // ── Chrome runtime presence ───────────────────────────────
    if (!window.chrome) {{
        window.chrome = {{
            runtime: {{ id: undefined }},
            loadTimes: () => ({{
                firstPaintTime: performance.now() / 1000 - Math.random(),
                requestTime:    Date.now() / 1000 - Math.random() * 2,
            }}),
            csi: () => ({{ startE: Date.now() - 500, onloadT: Date.now() - 100, pageT: Math.random() * 2000, tran: 15 }}),
            app: {{ isInstalled: false }},
        }};
    }}

    // ── Permission query spoof ────────────────────────────────
    const origQuery = window.navigator.permissions && window.navigator.permissions.query;
    if (origQuery) {{
        window.navigator.permissions.query = (params) => {{
            if (params.name === 'notifications') {{
                return Promise.resolve({{ state: Notification.permission }});
            }}
            return origQuery.call(navigator.permissions, params);
        }};
    }}
}})();
"""
