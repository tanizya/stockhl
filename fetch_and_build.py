#!/usr/bin/env python3
"""Fetch screener data and build a tabbed candlestick chart HTML page."""

import json
import yfinance as yf

TABS = [
    {
        "id": "market_cap",
        "label": "Market Cap Top 10",
        "predefined": None,  # custom query
    },
    {
        "id": "day_gainers",
        "label": "Top Gainers",
        "predefined": "day_gainers",
    },
    {
        "id": "most_actives",
        "label": "Most Actives",
        "predefined": "most_actives",
    },
    {
        "id": "most_shorted",
        "label": "Most Shorted",
        "predefined": "most_shorted_stocks",
    },
    {
        "id": "undervalued_large",
        "label": "Undervalued Large Caps",
        "predefined": "undervalued_large_caps",
    },
    {
        "id": "undervalued_growth",
        "label": "Undervalued Growth",
        "predefined": "undervalued_growth_stocks",
    },
]


def get_tickers_for_tab(tab: dict) -> list[str]:
    """Get up to 10 tickers for a given tab."""
    if tab["predefined"] is None:
        # Market cap top 10 via custom query
        q = yf.EquityQuery('and', [
            yf.EquityQuery('is-in', ['exchange', 'NMS', 'NYQ']),
            yf.EquityQuery('gt', ['intradaymarketcap', 100_000_000_000]),
        ])
        result = yf.screen(q, sortField='intradaymarketcap', sortAsc=False, size=20)
    else:
        result = yf.screen(tab["predefined"], count=25)

    tickers = []
    seen_names = set()
    for quote in result['quotes']:
        name = quote.get('shortName', '')
        if name in seen_names:
            continue
        seen_names.add(name)
        tickers.append(quote['symbol'])
        if len(tickers) == 10:
            break
    return tickers


def fetch_stock_data(ticker_symbol: str) -> dict:
    """Fetch 1-month daily OHLCV data for a given ticker."""
    tk = yf.Ticker(ticker_symbol)
    info = tk.info
    name = info.get("shortName", info.get("longName", ticker_symbol))
    market_cap = info.get("marketCap", 0)

    hist = tk.history(period="1mo", interval="1d")
    candles = []
    for date, row in hist.iterrows():
        candles.append({
            "time": date.strftime("%Y-%m-%d"),
            "open": round(row["Open"], 2),
            "high": round(row["High"], 2),
            "low": round(row["Low"], 2),
            "close": round(row["Close"], 2),
            "volume": int(row["Volume"]),
        })

    return {
        "ticker": ticker_symbol,
        "name": name,
        "marketCap": market_cap,
        "candles": candles,
    }


def build_html(all_data: dict, tabs: list[dict]) -> str:
    tabs_json = json.dumps(tabs, ensure_ascii=False)
    data_json = json.dumps(all_data, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Stock Screener - Candlestick Charts</title>
<script src="https://unpkg.com/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0f1117;
    color: #e1e4e8;
    min-height: 100vh;
    padding: 2px;
  }}
  .title-bar {{
    display: flex;
    align-items: baseline;
    justify-content: center;
    gap: 8px;
  }}
  .title-bar h1 {{
    font-size: 1.2rem;
    font-weight: 700;
    background: linear-gradient(135deg, #58a6ff, #8b5cf6);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }}
  .title-bar .subtitle {{
    font-size: 0.8rem;
    color: #6e7681;
  }}
  .tabs {{
    display: flex;
    justify-content: center;
    margin-bottom: 4px;
    border-bottom: 1px solid #21262d;
  }}
  .tab {{
    position: relative;
    padding: 6px 16px;
    border: none;
    background: transparent;
    color: #6e7681;
    font-size: 0.75rem;
    font-weight: 500;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    cursor: pointer;
    transition: color 0.15s;
  }}
  .tab::after {{
    content: '';
    position: absolute;
    bottom: -1px;
    left: 0;
    right: 0;
    height: 2px;
    background: transparent;
    transition: background 0.15s;
  }}
  .tab:hover {{
    color: #e1e4e8;
  }}
  .tab.active {{
    color: #58a6ff;
    font-weight: 600;
  }}
  .tab.active::after {{
    background: #58a6ff;
  }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
    gap: 2px;
    max-width: 1800px;
    margin: 0 auto;
  }}
  .card {{
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 4px;
    overflow: hidden;
    transition: transform 0.15s, box-shadow 0.15s;
  }}
  .card:hover {{
    box-shadow: 0 4px 16px rgba(0,0,0,0.3);
  }}
  .card-header {{
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 3px 6px;
    font-size: 0.8rem;
    white-space: nowrap;
    overflow: hidden;
  }}
  .ticker {{
    font-weight: 700;
    color: #f0f6fc;
  }}
  .company-name {{
    color: #8b949e;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
  }}
  .mcap {{
    color: #6e7681;
    flex-shrink: 0;
  }}
  .spacer {{ flex: 1; }}
  .pct {{
    font-weight: 600;
    flex-shrink: 0;
  }}
  .pct.up {{ color: #3fb950; }}
  .pct.down {{ color: #f85149; }}
  .pct-label {{
    color: #6e7681;
    font-size: 0.7rem;
    flex-shrink: 0;
  }}
  .chart-container {{
    width: 100%;
    height: 240px;
  }}
  .rank-badge {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background: #30363d;
    color: #8b949e;
    font-size: 0.7rem;
    font-weight: 700;
    margin-right: 8px;
  }}
  @media (max-width: 900px) {{
    .grid {{ grid-template-columns: 1fr; }}
    body {{ padding: 2px; }}
  }}
</style>
</head>
<body>
<div class="title-bar">
  <h1>Stock Screener</h1>
  <span class="subtitle">1-Month Daily Candlestick (Yahoo Finance)</span>
</div>
<div class="tabs" id="tabs"></div>
<div class="grid" id="grid"></div>

<script>
const tabs = {tabs_json};
const allData = {data_json};

function formatMcap(mc) {{
  if (mc >= 1e12) return '$' + (mc / 1e12).toFixed(1) + 'T';
  if (mc >= 1e9) return '$' + (mc / 1e9).toFixed(1) + 'B';
  if (mc >= 1e6) return '$' + (mc / 1e6).toFixed(0) + 'M';
  return '$' + mc.toLocaleString();
}}

const tabsContainer = document.getElementById('tabs');
const grid = document.getElementById('grid');
let activeCharts = [];
let syncing = false;

function renderTab(tabId) {{
  // Update tab buttons
  document.querySelectorAll('.tab').forEach(el => {{
    el.classList.toggle('active', el.dataset.id === tabId);
  }});

  // Cleanup previous charts
  activeCharts.forEach(c => c.chart.remove());
  activeCharts = [];
  grid.innerHTML = '';

  const stocks = allData[tabId] || [];
  stocks.forEach((stock, index) => {{
    const card = document.createElement('div');
    card.className = 'card';

    const candles = stock.candles;
    const n = candles.length;
    const first = n > 0 ? candles[0].open : 0;
    const last = n > 0 ? candles[n - 1].close : 0;
    const mo = first > 0 ? ((last - first) / first * 100) : 0;
    const moC = mo >= 0 ? 'up' : 'down';
    const moS = mo >= 0 ? '+' : '';
    const prevClose = n > 1 ? candles[n - 2].close : (n > 0 ? candles[0].open : 0);
    const day = prevClose > 0 ? ((last - prevClose) / prevClose * 100) : 0;
    const dayC = day >= 0 ? 'up' : 'down';
    const dayS = day >= 0 ? '+' : '';

    card.innerHTML = `
      <div class="card-header">
        <span class="rank-badge">${{index + 1}}</span>
        <span class="ticker">${{stock.ticker}}</span>
        <span class="company-name">${{stock.name}}</span>
        <span class="mcap">${{formatMcap(stock.marketCap)}}</span>
        <span class="spacer"></span>
        <span class="pct-label">1M</span><span class="pct ${{moC}}">${{moS}}${{mo.toFixed(1)}}%</span>
        <span class="pct-label">1D</span><span class="pct ${{dayC}}">${{dayS}}${{day.toFixed(1)}}%</span>
      </div>
      <div class="chart-container" id="chart-${{tabId}}-${{index}}"></div>
    `;
    grid.appendChild(card);

    const chartContainer = card.querySelector(`#chart-${{tabId}}-${{index}}`);
    const chart = LightweightCharts.createChart(chartContainer, {{
      width: chartContainer.clientWidth,
      height: 240,
      layout: {{
        background: {{ type: 'solid', color: '#161b22' }},
        textColor: '#8b949e',
        fontSize: 11,
      }},
      grid: {{
        vertLines: {{ color: '#21262d' }},
        horzLines: {{ color: '#21262d' }},
      }},
      crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
      rightPriceScale: {{ borderColor: '#30363d' }},
      timeScale: {{ borderColor: '#30363d', timeVisible: false }},
      handleScroll: false,
      handleScale: false,
    }});

    const series = chart.addCandlestickSeries({{
      upColor: '#3fb950',
      downColor: '#f85149',
      borderUpColor: '#3fb950',
      borderDownColor: '#f85149',
      wickUpColor: '#3fb950',
      wickDownColor: '#f85149',
    }});
    series.setData(candles);
    chart.timeScale().fitContent();

    activeCharts.push({{ chart, series }});

    const ro = new ResizeObserver(() => {{
      chart.applyOptions({{ width: chartContainer.clientWidth }});
    }});
    ro.observe(chartContainer);
  }});

  // Crosshair sync
  activeCharts.forEach((item, idx) => {{
    item.chart.subscribeCrosshairMove(param => {{
      if (syncing) return;
      syncing = true;
      activeCharts.forEach((other, otherIdx) => {{
        if (otherIdx === idx) return;
        if (!param.time) {{
          other.chart.clearCrosshairPosition();
        }} else {{
          other.chart.setCrosshairPosition(undefined, param.time, other.series);
        }}
      }});
      syncing = false;
    }});
  }});
}}

// Build tab buttons
tabs.forEach((tab, i) => {{
  const btn = document.createElement('button');
  btn.className = 'tab' + (i === 0 ? ' active' : '');
  btn.textContent = tab.label;
  btn.dataset.id = tab.id;
  btn.addEventListener('click', () => renderTab(tab.id));
  tabsContainer.appendChild(btn);
}});

// Render first tab
renderTab(tabs[0].id);
</script>
</body>
</html>"""


def main():
    all_data = {}

    for tab in TABS:
        print(f"\n[{tab['label']}] Fetching tickers...")
        tickers = get_tickers_for_tab(tab)
        print(f"  Found: {', '.join(tickers)}")

        stocks = []
        for i, ticker in enumerate(tickers):
            print(f"  [{i+1}/{len(tickers)}] {ticker}...", end=" ", flush=True)
            try:
                data = fetch_stock_data(ticker)
                stocks.append(data)
                last = data["candles"][-1]["close"] if data["candles"] else "N/A"
                print(f"OK ({len(data['candles'])} candles, last: {last})")
            except Exception as e:
                print(f"ERROR: {e}")

        stocks.sort(key=lambda s: s["marketCap"], reverse=True)
        all_data[tab["id"]] = stocks

    html = build_html(all_data, TABS)
    out_path = "index.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nDone! Generated {out_path} with {len(TABS)} tabs.")


if __name__ == "__main__":
    main()
