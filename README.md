# stockhl - Stock Screener

Yahoo Finance のスクリーナーデータを取得し、インタラクティブなローソク足チャートを表示する静的サイト。GitHub Actions で毎営業日自動更新し、GitHub Pages にデプロイされる。

## デモ

https://tanizya.github.io/stockhl/

## スクリーナータブ

| タブ | ソース |
|------|--------|
| Market Cap Top 10 | 時価総額 $100B 超を降順 |
| Top Gainers | Yahoo `day_gainers` |
| Most Actives | Yahoo `most_actives` |
| Most Shorted | Yahoo `most_shorted_stocks` |
| Undervalued Large Caps | Yahoo `undervalued_large_caps` |
| Undervalued Growth | Yahoo `undervalued_growth_stocks` |

各タブ 10 銘柄を表示。

## 機能

- **期間切替** — 1W(1H) / 1W / 1M / 3M / 6M / 1Y
- **出来高バー** — ローソク足下部にヒストグラム表示
- **移動平均線** — 日足 50/200MA、時間足 20/50MA
- **スパークラインモード** — グリッド一覧でトレンドを俯瞰
- **ウォッチリスト** — ★ ボタンで銘柄を保存 (localStorage)
- **レスポンシブ** — モバイル対応、スワイプでタブ切替
- **PWA** — オフライン対応、ホーム画面に追加可能
- **データキャッシュ** — API 失敗時にフォールバック、差分更新で高速化

## セットアップ

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## ローカル実行

```bash
python fetch_and_build.py
```

`_site/` ディレクトリに `index.html` 他が生成される。ブラウザで開いて確認:

```bash
open _site/index.html        # macOS
xdg-open _site/index.html    # Linux
```

## 自動デプロイ

GitHub Actions が平日 UTC 22:00 (米国東部 17:00、市場クローズ後) に自動実行:

1. `data_cache.json` をリストア
2. `python fetch_and_build.py` でデータ取得 & ビルド
3. `_site/` を GitHub Pages にデプロイ

手動実行: Actions タブから **Run workflow**。

## 技術スタック

- **Python** + [yfinance](https://github.com/ranaroussi/yfinance) — データ取得・HTML 生成
- **[Lightweight Charts](https://github.com/nicehash/lightweight-charts)** v4.1.1 (CDN) — ローソク足・出来高・MA 描画
- **Canvas API** — スパークライン描画
- **GitHub Actions** + **GitHub Pages** — CI/CD・ホスティング

## プロジェクト構成

```
stockhl/
  fetch_and_build.py          # データ取得 + HTML/PWA 生成 (全ロジック)
  requirements.txt             # yfinance
  .github/workflows/update.yml # CI/CD
  .gitignore
  _site/                       # 生成物 (gitignore)
    index.html
    manifest.json
    sw.js
    icon-192.png
    icon-512.png
  data_cache.json              # キャッシュ (gitignore)
```
