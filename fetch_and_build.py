#!/usr/bin/env python3
"""Fetch screener data and build a tabbed candlestick chart HTML page.

Features:
  #1  Last-updated timestamp
  #2  Responsive layout (tab scroll, mobile chart height, swipe)
  #3  Period switching (1W_1H / 1W / 1M / 3M / 6M / 1Y)
  #4  Volume histogram bars
  #5  Moving averages (daily 50/200 MA, hourly 20/50 MA)
  #6  Data cache with fallback
  #7  Diff update (skip unchanged tabs)
  #8  Mini sparkline grid view
  #9  Watchlist (localStorage)
  #10 PWA (manifest, service worker, icons)
"""

import json
import os
import struct
import zlib
from datetime import datetime, timezone

import yfinance as yf

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TABS = [
    {"id": "market_cap", "label": "Market Cap Top 10", "predefined": None},
    {"id": "day_gainers", "label": "Top Gainers", "predefined": "day_gainers"},
    {"id": "most_actives", "label": "Most Actives", "predefined": "most_actives"},
    {"id": "most_shorted", "label": "Most Shorted", "predefined": "most_shorted_stocks"},
    {"id": "undervalued_large", "label": "Undervalued Large Caps", "predefined": "undervalued_large_caps"},
    {"id": "undervalued_growth", "label": "Undervalued Growth", "predefined": "undervalued_growth_stocks"},
]

# Display bars per daily period
DAILY_BARS = {"1W": 5, "1M": 22, "3M": 66, "6M": 132, "1Y": 252}
# Which MAs to show per daily period
DAILY_MA = {"1W": [50], "1M": [50], "3M": [50], "6M": [50, 200], "1Y": [50, 200]}
# Hourly period
HOURLY_BARS = 33  # ~5 trading days
HOURLY_MA = [20, 50]

CACHE_FILE = "data_cache.json"
SITE_DIR = "_site"

# Period config passed to JavaScript
PERIODS_JS = [
    {"key": "1W_1H", "label": "1W(1H)"},
    {"key": "1W", "label": "1W"},
    {"key": "1M", "label": "1M"},
    {"key": "3M", "label": "3M"},
    {"key": "6M", "label": "6M"},
    {"key": "1Y", "label": "1Y"},
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def calculate_ma(closes: list[float], window: int) -> list[float | None]:
    """Simple moving average. Returns None for positions with insufficient data."""
    result: list[float | None] = []
    for i in range(len(closes)):
        if i < window - 1:
            result.append(None)
        else:
            avg = sum(closes[i - window + 1 : i + 1]) / window
            result.append(round(avg, 2))
    return result


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


def get_tickers_for_tab(tab: dict) -> list[str]:
    """Get up to 10 tickers for a given tab."""
    if tab["predefined"] is None:
        q = yf.EquityQuery(
            "and",
            [
                yf.EquityQuery("is-in", ["exchange", "NMS", "NYQ"]),
                yf.EquityQuery("gt", ["intradaymarketcap", 100_000_000_000]),
            ],
        )
        result = yf.screen(q, sortField="intradaymarketcap", sortAsc=False, size=20)
    else:
        result = yf.screen(tab["predefined"], count=25)

    tickers: list[str] = []
    seen_names: set[str] = set()
    for quote in result["quotes"]:
        name = quote.get("shortName", "")
        if name in seen_names:
            continue
        seen_names.add(name)
        tickers.append(quote["symbol"])
        if len(tickers) == 10:
            break
    return tickers


def _build_ma_points(candles, ma_values):
    """Build list of {time, value} for non-None MA values aligned to candles."""
    return [
        {"time": c["time"], "value": v}
        for c, v in zip(candles, ma_values)
        if v is not None
    ]


def _build_periods(daily_candles: list[dict], hourly_candles: list[dict]) -> dict:
    """Build all period data with MAs from raw candle arrays."""
    periods: dict = {}

    # -- Daily periods --
    if daily_candles:
        daily_closes = [c["close"] for c in daily_candles]
        ma50_full = calculate_ma(daily_closes, 50)
        ma200_full = calculate_ma(daily_closes, 200)

        for key, num_bars in DAILY_BARS.items():
            display = daily_candles[-num_bars:]
            offset = len(daily_candles) - len(display)

            ma_data: dict = {}
            if 50 in DAILY_MA[key]:
                pts = _build_ma_points(display, ma50_full[offset : offset + len(display)])
                if pts:
                    ma_data["50"] = pts
            if 200 in DAILY_MA[key]:
                pts = _build_ma_points(display, ma200_full[offset : offset + len(display)])
                if pts:
                    ma_data["200"] = pts

            periods[key] = {"interval": "1d", "candles": display, "ma": ma_data}

    # -- Hourly period (1W_1H) --
    if hourly_candles:
        display_h = hourly_candles[-HOURLY_BARS:]
        offset_h = len(hourly_candles) - len(display_h)

        h_closes = [c["close"] for c in hourly_candles]
        ma20_full = calculate_ma(h_closes, 20)
        ma50_full_h = calculate_ma(h_closes, 50)

        ma_data_h: dict = {}
        pts20 = _build_ma_points(display_h, ma20_full[offset_h : offset_h + len(display_h)])
        if pts20:
            ma_data_h["20"] = pts20
        pts50 = _build_ma_points(display_h, ma50_full_h[offset_h : offset_h + len(display_h)])
        if pts50:
            ma_data_h["50"] = pts50

        periods["1W_1H"] = {"interval": "1h", "candles": display_h, "ma": ma_data_h}

    return periods


def fetch_stock_data(ticker_symbol: str) -> dict:
    """Fetch all period data for a single ticker."""
    tk = yf.Ticker(ticker_symbol)
    info = tk.info
    name = info.get("shortName", info.get("longName", ticker_symbol))
    market_cap = info.get("marketCap", 0)

    # 2-year daily data (for 200MA on 1Y)
    daily_hist = tk.history(period="2y", interval="1d")
    daily_candles = []
    for date, row in daily_hist.iterrows():
        daily_candles.append(
            {
                "time": date.strftime("%Y-%m-%d"),
                "open": round(row["Open"], 2),
                "high": round(row["High"], 2),
                "low": round(row["Low"], 2),
                "close": round(row["Close"], 2),
                "volume": int(row["Volume"]),
            }
        )

    # 1-month hourly data (for 1W_1H with 50-period MA)
    hourly_candles = []
    try:
        hourly_hist = tk.history(period="1mo", interval="1h")
        for date, row in hourly_hist.iterrows():
            hourly_candles.append(
                {
                    "time": int(date.timestamp()),
                    "open": round(row["Open"], 2),
                    "high": round(row["High"], 2),
                    "low": round(row["Low"], 2),
                    "close": round(row["Close"], 2),
                    "volume": int(row["Volume"]),
                }
            )
    except Exception:
        pass  # hourly data unavailable for some tickers

    periods = _build_periods(daily_candles, hourly_candles)

    return {
        "ticker": ticker_symbol,
        "name": name,
        "marketCap": market_cap,
        "periods": periods,
    }


# ---------------------------------------------------------------------------
# Cache (#6, #7)
# ---------------------------------------------------------------------------


def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_cache(data: dict):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def fetch_all_data(cached_data: dict | None = None) -> tuple[dict, dict]:
    """Fetch data for all tabs, with diff-update and fallback support."""
    if cached_data is None:
        cached_data = {}

    all_data: dict = {}
    cache_out: dict = {}

    for tab in TABS:
        print(f"\n[{tab['label']}] Fetching tickers...")
        try:
            tickers = get_tickers_for_tab(tab)
        except Exception as e:
            print(f"  ERROR fetching tickers: {e}")
            # Fallback to cache
            cached_tab = cached_data.get(tab["id"], {})
            if cached_tab.get("stocks"):
                print("  -> Using fully cached tab data")
                all_data[tab["id"]] = cached_tab["stocks"]
                cache_out[tab["id"]] = cached_tab
            continue

        print(f"  Found: {', '.join(tickers)}")

        # Diff update (#7): reuse cache if ticker list is unchanged
        cached_tab = cached_data.get(tab["id"], {})
        cached_tickers = cached_tab.get("tickers", [])
        if tickers == cached_tickers and cached_tab.get("stocks"):
            print("  -> Ticker list unchanged, using cache")
            all_data[tab["id"]] = cached_tab["stocks"]
            cache_out[tab["id"]] = cached_tab
            continue

        stocks: list[dict] = []
        for i, ticker in enumerate(tickers):
            print(f"  [{i + 1}/{len(tickers)}] {ticker}...", end=" ", flush=True)
            try:
                data = fetch_stock_data(ticker)
                stocks.append(data)
                p1m = data["periods"].get("1M", {})
                candles = p1m.get("candles", [])
                last = candles[-1]["close"] if candles else "N/A"
                print(f"OK ({len(candles)} 1M candles, last: {last})")
            except Exception as e:
                print(f"ERROR: {e}")
                # Fallback: try cached version of this ticker
                for cs in cached_tab.get("stocks", []):
                    if cs["ticker"] == ticker:
                        stocks.append(cs)
                        print(f"  -> Using cached data for {ticker}")
                        break

        stocks.sort(key=lambda s: s["marketCap"], reverse=True)
        all_data[tab["id"]] = stocks
        cache_out[tab["id"]] = {"tickers": tickers, "stocks": stocks}

    return all_data, cache_out


# ---------------------------------------------------------------------------
# PWA assets (#10)
# ---------------------------------------------------------------------------


def _make_png_chunk(ctype: bytes, data: bytes) -> bytes:
    raw = ctype + data
    crc = struct.pack(">I", zlib.crc32(raw) & 0xFFFFFFFF)
    return struct.pack(">I", len(data)) + raw + crc


def create_png_icon(size: int) -> bytes:
    """Generate a simple PNG icon with a chart silhouette."""
    pixels = bytearray()
    for y in range(size):
        pixels.append(0)  # row filter: None
        for x in range(size):
            # Normalised coordinates
            cx = x / size
            cy = y / size
            # Dark background
            r, g, b, a = 18, 22, 34, 255
            # Chart area
            margin = 0.18
            if margin <= cx <= 1 - margin and margin <= cy <= 1 - margin:
                ncx = (cx - margin) / (1 - 2 * margin)
                ncy = (cy - margin) / (1 - 2 * margin)
                line_y = 1.0 - (0.25 + 0.5 * ncx)
                if abs(ncy - line_y) < 0.035:
                    r, g, b = 88, 166, 255
                elif ncy > line_y:
                    r = int(18 * 0.7 + 88 * 0.3)
                    g = int(22 * 0.7 + 166 * 0.3)
                    b = int(34 * 0.7 + 255 * 0.3)
            pixels.extend([r, g, b, a])

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(pixels), 9)
    png = b"\x89PNG\r\n\x1a\n"
    png += _make_png_chunk(b"IHDR", ihdr)
    png += _make_png_chunk(b"IDAT", idat)
    png += _make_png_chunk(b"IEND", b"")
    return png


def write_manifest(out_dir: str):
    manifest = {
        "name": "Stock Screener",
        "short_name": "StockHL",
        "start_url": ".",
        "display": "standalone",
        "background_color": "#0f1117",
        "theme_color": "#0f1117",
        "icons": [
            {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def write_service_worker(out_dir: str, version: str):
    sw = f"""const CACHE_NAME='stockhl-{version}';
const ASSETS=['./','/index.html','/manifest.json','/icon-192.png','/icon-512.png'];
self.addEventListener('install',e=>{{e.waitUntil(caches.open(CACHE_NAME).then(c=>c.addAll(ASSETS)));self.skipWaiting();}});
self.addEventListener('activate',e=>{{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==CACHE_NAME).map(k=>caches.delete(k)))));self.clients.claim();}});
self.addEventListener('fetch',e=>{{e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request)));}});"""
    with open(os.path.join(out_dir, "sw.js"), "w", encoding="utf-8") as f:
        f.write(sw)


def write_icons(out_dir: str):
    for size in (192, 512):
        path = os.path.join(out_dir, f"icon-{size}.png")
        if not os.path.exists(path):
            print(f"  Generating icon-{size}.png...")
            with open(path, "wb") as f:
                f.write(create_png_icon(size))


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------


def build_html(all_data: dict, tabs: list[dict], timestamp: str) -> str:
    tabs_json = json.dumps(tabs, ensure_ascii=False)
    data_json = json.dumps(all_data, ensure_ascii=False)
    periods_json = json.dumps(PERIODS_JS, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Stock Screener - Candlestick Charts</title>
<link rel="manifest" href="manifest.json">
<meta name="theme-color" content="#0f1117">
<link rel="icon" type="image/png" sizes="192x192" href="icon-192.png">
<link rel="apple-touch-icon" href="icon-192.png">
<script src="https://unpkg.com/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0f1117;color:#e1e4e8;min-height:100vh;padding:2px}}
.title-bar{{display:flex;align-items:baseline;justify-content:center;gap:8px;flex-wrap:wrap}}
.title-bar h1{{font-size:1.2rem;font-weight:700;background:linear-gradient(135deg,#58a6ff,#8b5cf6);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.title-bar .subtitle{{font-size:0.75rem;color:#6e7681}}

/* Tabs – horizontal scroll on mobile */
.tabs{{display:flex;margin-bottom:0;border-bottom:1px solid #21262d;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none}}
.tabs::-webkit-scrollbar{{display:none}}
.tab{{position:relative;padding:8px 16px;border:none;background:transparent;color:#6e7681;font-size:0.75rem;font-weight:500;letter-spacing:.04em;text-transform:uppercase;cursor:pointer;transition:color .15s;white-space:nowrap;min-height:44px;display:flex;align-items:center}}
.tab::after{{content:'';position:absolute;bottom:-1px;left:0;right:0;height:2px;background:transparent;transition:background .15s}}
.tab:hover{{color:#e1e4e8}}
.tab.active{{color:#58a6ff;font-weight:600}}
.tab.active::after{{background:#58a6ff}}

/* Controls bar */
.controls{{display:flex;justify-content:center;align-items:center;gap:12px;padding:6px 0 4px;flex-wrap:wrap}}
.period-bar{{display:flex;gap:3px}}
.period-btn{{padding:4px 10px;border:1px solid #30363d;border-radius:12px;background:transparent;color:#8b949e;font-size:0.7rem;cursor:pointer;transition:all .15s;min-height:32px}}
.period-btn:hover{{color:#e1e4e8;border-color:#58a6ff}}
.period-btn.active{{background:#58a6ff;color:#0f1117;border-color:#58a6ff;font-weight:600}}
.mode-toggle{{display:flex;gap:3px}}
.mode-btn{{padding:4px 10px;border:1px solid #30363d;border-radius:12px;background:transparent;color:#8b949e;font-size:0.7rem;cursor:pointer;transition:all .15s;min-height:32px}}
.mode-btn:hover{{color:#e1e4e8}}
.mode-btn.active{{background:#30363d;color:#e1e4e8}}
.ma-legend{{display:flex;gap:8px;font-size:0.65rem;color:#8b949e}}
.ma-legend span{{display:flex;align-items:center;gap:3px}}

/* Card grid */
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(380px,1fr));gap:2px;max-width:1800px;margin:0 auto}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:4px;overflow:hidden;transition:transform .15s,box-shadow .15s}}
.card:hover{{box-shadow:0 4px 16px rgba(0,0,0,.3)}}
.card-header{{display:flex;align-items:center;gap:6px;padding:3px 6px;font-size:0.8rem;white-space:nowrap;overflow:hidden}}
.rank-badge{{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:50%;background:#30363d;color:#8b949e;font-size:.7rem;font-weight:700;flex-shrink:0}}
.ticker{{font-weight:700;color:#f0f6fc}}
.company-name{{color:#8b949e;overflow:hidden;text-overflow:ellipsis;min-width:0}}
.mcap{{color:#6e7681;flex-shrink:0}}
.spacer{{flex:1}}
.pct{{font-weight:600;flex-shrink:0}}
.pct.up{{color:#3fb950}}.pct.down{{color:#f85149}}
.pct-label{{color:#6e7681;font-size:.7rem;flex-shrink:0}}
.chart-container{{width:100%;height:240px}}

/* Star (watchlist) */
.star-btn{{background:none;border:none;cursor:pointer;color:#6e7681;font-size:1rem;padding:2px 4px;flex-shrink:0;transition:color .15s}}
.star-btn:hover{{color:#f0c000}}
.star-btn.active{{color:#f0c000}}

/* Sparkline grid */
.sparkline-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:4px;max-width:1800px;margin:0 auto}}
.sparkline-card{{background:#161b22;border:1px solid #30363d;border-radius:4px;padding:6px;overflow:hidden}}
.sparkline-header{{display:flex;align-items:center;gap:4px;font-size:.75rem;margin-bottom:4px;white-space:nowrap;overflow:hidden}}
.sparkline-header .ticker{{font-size:.75rem}}
.sparkline-header .company-name{{font-size:.7rem;overflow:hidden;text-overflow:ellipsis;min-width:0}}
.sparkline-body{{display:flex;align-items:center;gap:6px}}
.sparkline-canvas{{flex:1;min-width:0}}
.sparkline-stats{{text-align:right;font-size:.7rem;flex-shrink:0}}
.sparkline-price{{display:block;color:#f0f6fc;font-weight:600}}

/* Responsive */
@media(max-width:900px){{
  .grid{{grid-template-columns:1fr}}
  .chart-container{{height:200px!important}}
  body{{padding:2px}}
  .controls{{gap:6px;padding:4px 2px}}
}}
@media(max-width:600px){{
  .tab{{padding:6px 10px;font-size:.65rem}}
  .sparkline-grid{{grid-template-columns:repeat(auto-fill,minmax(160px,1fr))}}
}}
</style>
</head>
<body>
<div class="title-bar">
  <h1>Stock Screener</h1>
  <span class="subtitle">Updated: {timestamp}</span>
</div>
<div class="tabs" id="tabs"></div>
<div class="controls">
  <div class="period-bar" id="period-bar"></div>
  <div class="ma-legend" id="ma-legend"></div>
  <div class="mode-toggle">
    <button class="mode-btn active" data-mode="charts" id="mode-charts">Charts</button>
    <button class="mode-btn" data-mode="sparklines" id="mode-sparklines">Sparklines</button>
  </div>
</div>
<div class="grid" id="grid"></div>
<div class="sparkline-grid" id="sparkline-grid" style="display:none"></div>

<script>
/* === Data === */
const tabs = {tabs_json};
const allData = {data_json};
const periodConfig = {periods_json};

/* === State === */
let currentTab = tabs[0].id;
let currentPeriod = '1M';
let viewMode = 'charts';
let activeCharts = [];
let syncing = false;
let watchlist = JSON.parse(localStorage.getItem('stockhl_watchlist') || '[]');

/* === DOM refs === */
const tabsEl = document.getElementById('tabs');
const periodBar = document.getElementById('period-bar');
const maLegend = document.getElementById('ma-legend');
const gridEl = document.getElementById('grid');
const sparkEl = document.getElementById('sparkline-grid');
const modeChartsBtn = document.getElementById('mode-charts');
const modeSparklinesBtn = document.getElementById('mode-sparklines');

/* === Helpers === */
const MA_COLORS = {{'20':'#f0c000','50':'#ff9800','200':'#9c27b0'}};

function formatMcap(mc) {{
  if (mc >= 1e12) return '$' + (mc / 1e12).toFixed(1) + 'T';
  if (mc >= 1e9) return '$' + (mc / 1e9).toFixed(1) + 'B';
  if (mc >= 1e6) return '$' + (mc / 1e6).toFixed(0) + 'M';
  return '$' + mc.toLocaleString();
}}

function saveWatchlist() {{ localStorage.setItem('stockhl_watchlist', JSON.stringify(watchlist)); }}

function toggleWatch(ticker) {{
  const idx = watchlist.indexOf(ticker);
  if (idx >= 0) watchlist.splice(idx, 1); else watchlist.push(ticker);
  saveWatchlist();
  if (currentTab === 'watchlist') {{ render(); return; }}
  document.querySelectorAll('.star-btn').forEach(b => {{
    b.classList.toggle('active', watchlist.includes(b.dataset.ticker));
  }});
}}

function getStocks(tabId) {{
  if (tabId === 'watchlist') {{
    const all = []; const seen = new Set();
    for (const tid in allData) {{
      for (const s of allData[tid]) {{
        if (watchlist.includes(s.ticker) && !seen.has(s.ticker)) {{ all.push(s); seen.add(s.ticker); }}
      }}
    }}
    return all;
  }}
  return allData[tabId] || [];
}}

/* === Build tabs === */
function buildTabs() {{
  tabsEl.innerHTML = '';
  const allTabs = [...tabs, {{id:'watchlist', label:'★ Watchlist'}}];
  allTabs.forEach(tab => {{
    const btn = document.createElement('button');
    btn.className = 'tab' + (tab.id === currentTab ? ' active' : '');
    btn.textContent = tab.label;
    btn.dataset.id = tab.id;
    btn.addEventListener('click', () => {{ currentTab = tab.id; render(); }});
    tabsEl.appendChild(btn);
  }});
}}

/* === Build period bar === */
function buildPeriodBar() {{
  periodBar.innerHTML = '';
  periodConfig.forEach(p => {{
    const btn = document.createElement('button');
    btn.className = 'period-btn' + (p.key === currentPeriod ? ' active' : '');
    btn.textContent = p.label;
    btn.addEventListener('click', () => {{ currentPeriod = p.key; render(); }});
    periodBar.appendChild(btn);
  }});
}}

/* === MA legend === */
function updateMaLegend() {{
  const isH = currentPeriod === '1W_1H';
  const has200 = ['6M','1Y'].includes(currentPeriod);
  let html = '';
  if (isH) {{
    html = '<span><span style="color:#f0c000">━</span> 20MA</span><span><span style="color:#ff9800">━</span> 50MA</span>';
  }} else if (has200) {{
    html = '<span><span style="color:#ff9800">━</span> 50MA</span><span><span style="color:#9c27b0">━</span> 200MA</span>';
  }} else {{
    html = '<span><span style="color:#ff9800">━</span> 50MA</span>';
  }}
  maLegend.innerHTML = html;
}}

/* === Chart rendering === */
function renderCharts(stocks) {{
  activeCharts.forEach(c => c.chart.remove());
  activeCharts = [];
  gridEl.innerHTML = '';

  const isHourly = currentPeriod === '1W_1H';
  const chartH = window.innerWidth <= 900 ? 200 : 240;

  stocks.forEach((stock, index) => {{
    const pd = stock.periods[currentPeriod];
    if (!pd || !pd.candles || pd.candles.length === 0) return;

    const candles = pd.candles;
    const ma = pd.ma || {{}};
    const n = candles.length;
    const first = candles[0].open;
    const last = candles[n - 1].close;
    const pctPeriod = first > 0 ? ((last - first) / first * 100) : 0;
    const prevClose = n > 1 ? candles[n - 2].close : first;
    const pctDay = prevClose > 0 ? ((last - prevClose) / prevClose * 100) : 0;

    const card = document.createElement('div');
    card.className = 'card';
    const periodLabel = currentPeriod === '1W_1H' ? '1W' : currentPeriod;
    card.innerHTML = `
      <div class="card-header">
        <span class="rank-badge">${{index + 1}}</span>
        <button class="star-btn ${{watchlist.includes(stock.ticker)?'active':''}}" data-ticker="${{stock.ticker}}">★</button>
        <span class="ticker">${{stock.ticker}}</span>
        <span class="company-name">${{stock.name}}</span>
        <span class="mcap">${{formatMcap(stock.marketCap)}}</span>
        <span class="spacer"></span>
        <span class="pct-label">${{periodLabel}}</span><span class="pct ${{pctPeriod>=0?'up':'down'}}">${{pctPeriod>=0?'+':''}}${{pctPeriod.toFixed(1)}}%</span>
        <span class="pct-label">1D</span><span class="pct ${{pctDay>=0?'up':'down'}}">${{pctDay>=0?'+':''}}${{pctDay.toFixed(1)}}%</span>
      </div>
      <div class="chart-container" id="cc-${{currentTab}}-${{index}}"></div>
    `;
    gridEl.appendChild(card);

    const container = card.querySelector('.chart-container');
    const chart = LightweightCharts.createChart(container, {{
      width: container.clientWidth,
      height: chartH,
      layout: {{ background: {{ type: 'solid', color: '#161b22' }}, textColor: '#8b949e', fontSize: 11 }},
      grid: {{ vertLines: {{ color: '#21262d' }}, horzLines: {{ color: '#21262d' }} }},
      crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
      rightPriceScale: {{ borderColor: '#30363d' }},
      timeScale: {{ borderColor: '#30363d', timeVisible: isHourly, secondsVisible: false }},
      handleScroll: false,
      handleScale: false,
    }});

    /* Candlestick */
    const candleSeries = chart.addCandlestickSeries({{
      upColor: '#3fb950', downColor: '#f85149',
      borderUpColor: '#3fb950', borderDownColor: '#f85149',
      wickUpColor: '#3fb950', wickDownColor: '#f85149',
    }});
    candleSeries.setData(candles);

    /* Volume (#4) */
    const volSeries = chart.addHistogramSeries({{
      priceFormat: {{ type: 'volume' }},
      priceScaleId: 'vol',
    }});
    chart.priceScale('vol').applyOptions({{ scaleMargins: {{ top: 0.8, bottom: 0 }} }});
    volSeries.setData(candles.map(c => ({{
      time: c.time,
      value: c.volume,
      color: c.close >= c.open ? 'rgba(63,185,80,0.25)' : 'rgba(248,81,73,0.25)',
    }})));

    /* Moving Averages (#5) */
    const maSeries = [];
    for (const [maKey, points] of Object.entries(ma)) {{
      if (points.length === 0) continue;
      const ls = chart.addLineSeries({{
        color: MA_COLORS[maKey] || '#888',
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      }});
      ls.setData(points);
      maSeries.push(ls);
    }}

    chart.timeScale().fitContent();
    activeCharts.push({{ chart, candleSeries, volSeries, maSeries }});

    new ResizeObserver(() => {{
      chart.applyOptions({{ width: container.clientWidth }});
    }}).observe(container);
  }});

  /* Crosshair sync */
  activeCharts.forEach((item, idx) => {{
    item.chart.subscribeCrosshairMove(param => {{
      if (syncing) return;
      syncing = true;
      activeCharts.forEach((other, oi) => {{
        if (oi === idx) return;
        if (!param.time) other.chart.clearCrosshairPosition();
        else other.chart.setCrosshairPosition(undefined, param.time, other.candleSeries);
      }});
      syncing = false;
    }});
  }});
}}

/* === Sparkline rendering (#8) === */
function drawSparkline(canvas, prices) {{
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  if (prices.length < 2) return;
  const min = Math.min(...prices), max = Math.max(...prices);
  const range = max - min || 1;
  const pad = 2;
  const color = prices[prices.length-1] >= prices[0] ? '#3fb950' : '#f85149';
  const pts = prices.map((p,i) => ({{
    x: (i / (prices.length - 1)) * w,
    y: h - pad - ((p - min) / range) * (h - 2*pad),
  }}));
  ctx.clearRect(0, 0, w, h);
  ctx.beginPath();
  pts.forEach((pt,i) => i === 0 ? ctx.moveTo(pt.x, pt.y) : ctx.lineTo(pt.x, pt.y));
  ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath();
  ctx.fillStyle = color === '#3fb950' ? 'rgba(63,185,80,0.12)' : 'rgba(248,81,73,0.12)';
  ctx.fill();
  ctx.beginPath();
  pts.forEach((pt,i) => i === 0 ? ctx.moveTo(pt.x, pt.y) : ctx.lineTo(pt.x, pt.y));
  ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.stroke();
}}

function renderSparklines(stocks) {{
  sparkEl.innerHTML = '';
  stocks.forEach(stock => {{
    const pd = stock.periods[currentPeriod];
    if (!pd || !pd.candles || pd.candles.length < 2) return;
    const prices = pd.candles.map(c => c.close);
    const last = prices[prices.length - 1];
    const pct = prices[0] > 0 ? ((last - prices[0]) / prices[0] * 100) : 0;

    const card = document.createElement('div');
    card.className = 'sparkline-card';
    card.innerHTML = `
      <div class="sparkline-header">
        <button class="star-btn ${{watchlist.includes(stock.ticker)?'active':''}}" data-ticker="${{stock.ticker}}">★</button>
        <span class="ticker">${{stock.ticker}}</span>
        <span class="company-name">${{stock.name}}</span>
      </div>
      <div class="sparkline-body">
        <div class="sparkline-canvas"><canvas width="160" height="40"></canvas></div>
        <div class="sparkline-stats">
          <span class="sparkline-price">$${{last.toFixed(2)}}</span>
          <span class="pct ${{pct>=0?'up':'down'}}">${{pct>=0?'+':''}}${{pct.toFixed(1)}}%</span>
        </div>
      </div>
    `;
    sparkEl.appendChild(card);
    drawSparkline(card.querySelector('canvas'), prices);
  }});
}}

/* === Main render === */
function render() {{
  buildTabs();
  buildPeriodBar();
  updateMaLegend();
  modeChartsBtn.classList.toggle('active', viewMode === 'charts');
  modeSparklinesBtn.classList.toggle('active', viewMode === 'sparklines');
  const stocks = getStocks(currentTab);
  if (viewMode === 'charts') {{
    gridEl.style.display = ''; sparkEl.style.display = 'none';
    renderCharts(stocks);
  }} else {{
    gridEl.style.display = 'none'; sparkEl.style.display = '';
    renderSparklines(stocks);
  }}
}}

/* === Event listeners === */
modeChartsBtn.addEventListener('click', () => {{ viewMode = 'charts'; render(); }});
modeSparklinesBtn.addEventListener('click', () => {{ viewMode = 'sparklines'; render(); }});

/* Star buttons – event delegation */
document.addEventListener('click', e => {{
  const btn = e.target.closest('.star-btn');
  if (btn && btn.dataset.ticker) toggleWatch(btn.dataset.ticker);
}});

/* Swipe to switch tabs (#2) */
let touchX0 = 0, touchY0 = 0;
document.addEventListener('touchstart', e => {{ touchX0 = e.touches[0].clientX; touchY0 = e.touches[0].clientY; }});
document.addEventListener('touchend', e => {{
  const dx = e.changedTouches[0].clientX - touchX0;
  const dy = e.changedTouches[0].clientY - touchY0;
  if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) {{
    const ids = [...tabs.map(t => t.id), 'watchlist'];
    const ci = ids.indexOf(currentTab);
    if (dx > 0 && ci > 0) {{ currentTab = ids[ci - 1]; render(); }}
    else if (dx < 0 && ci < ids.length - 1) {{ currentTab = ids[ci + 1]; render(); }}
  }}
}});

/* Service Worker registration (#10) */
if ('serviceWorker' in navigator) {{
  navigator.serviceWorker.register('sw.js').catch(() => {{}});
}}

/* Initial render */
render();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    os.makedirs(SITE_DIR, exist_ok=True)

    # Load cache (#6)
    cached_data = load_cache()

    # Fetch data (#7 diff update)
    all_data, cache_out = fetch_all_data(cached_data)

    # Save cache
    save_cache(cache_out)

    # Build HTML (all features)
    html = build_html(all_data, TABS, timestamp)
    html_path = os.path.join(SITE_DIR, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    # PWA assets (#10)
    write_manifest(SITE_DIR)
    write_service_worker(SITE_DIR, timestamp.replace(" ", "-").replace(":", ""))
    write_icons(SITE_DIR)

    print(f"\nDone! Generated {SITE_DIR}/ with {len(TABS)} tabs. ({timestamp})")


if __name__ == "__main__":
    main()
