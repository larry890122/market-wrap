from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import urllib.parse
import urllib.request


USER_AGENT = "Mozilla/5.0"
UTC = dt.timezone.utc

LABELS_ZH = {
    "S&P 500": "S&P 500",
    "Dow Jones": "道瓊工業指數",
    "Nasdaq Composite": "那斯達克綜合指數",
    "Russell 2000": "羅素 2000",
    "VIX": "VIX",
    "US 10Y Treasury": "美國 10 年期公債殖利率",
    "DXY": "美元指數",
    "WTI Front": "WTI 原油近月",
    "Technology": "科技",
    "Financials": "金融",
    "Energy": "能源",
    "Health Care": "醫療保健",
    "Industrials": "工業",
    "Consumer Discretionary": "非必需消費",
    "Consumer Staples": "必需消費",
    "Utilities": "公用事業",
    "Materials": "原物料",
    "Real Estate": "不動產",
    "Communication Services": "通訊服務",
    "Apple": "Apple",
    "Microsoft": "Microsoft",
    "NVIDIA": "NVIDIA",
    "Amazon": "Amazon",
    "Alphabet": "Alphabet",
    "Meta": "Meta",
    "Tesla": "Tesla",
    "Broadcom": "Broadcom",
    "FTSE 100": "FTSE 100",
    "CAC 40": "CAC 40",
    "DAX": "DAX",
}


def load_config(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config-path",
        default=str(pathlib.Path(__file__).resolve().parent / "market_wrap_yahoo_config.json"),
    )
    parser.add_argument(
        "--output-dir",
        default=str(pathlib.Path(__file__).resolve().parent / "output"),
    )
    parser.add_argument(
        "--market",
        choices=["all", "us", "europe"],
        default="all",
    )
    parser.add_argument("--as-of-date")
    return parser.parse_args()


def parse_as_of_date(raw: str | None) -> dt.date:
    if raw:
        return dt.date.fromisoformat(raw)
    return dt.datetime.now(UTC).date()


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch_series(symbol: str, start: dt.date, end: dt.date, price_scale: float = 1.0) -> list[tuple[dt.date, float]]:
    period1 = int(dt.datetime.combine(start, dt.time.min, tzinfo=UTC).timestamp())
    period2 = int(dt.datetime.combine(end + dt.timedelta(days=1), dt.time.min, tzinfo=UTC).timestamp())
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
        f"?period1={period1}&period2={period2}&interval=1d&includePrePost=false&events=div%2Csplits"
    )
    payload = fetch_json(url)
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        raise RuntimeError(f"Yahoo Finance returned no chart result for {symbol}.")

    row = result[0]
    timestamps = row.get("timestamp") or []
    closes = (((row.get("indicators") or {}).get("quote") or [{}])[0].get("close")) or []

    series: list[tuple[dt.date, float]] = []
    for timestamp, close in zip(timestamps, closes):
        if close is None:
            continue
        price_date = dt.datetime.fromtimestamp(timestamp, UTC).date()
        series.append((price_date, round(float(close) * price_scale, 6)))

    series.sort(key=lambda item: item[0])
    if not series:
        raise RuntimeError(f"Yahoo Finance returned empty price series for {symbol}.")
    return series


def get_point_on_or_before(series: list[tuple[dt.date, float]], target_date: dt.date) -> tuple[dt.date, float] | None:
    eligible = [item for item in series if item[0] <= target_date]
    return eligible[-1] if eligible else None


def get_previous_point(series: list[tuple[dt.date, float]], target_date: dt.date) -> tuple[dt.date, float] | None:
    eligible = [item for item in series if item[0] < target_date]
    return eligible[-1] if eligible else None


def build_row(item: dict, series_by_symbol: dict[str, list[tuple[dt.date, float]]], summary_date: dt.date) -> dict | None:
    symbol = item["symbol"]
    series = series_by_symbol.get(symbol)
    if not series:
        return None

    current = get_point_on_or_before(series, summary_date)
    if not current:
        return None

    previous = get_previous_point(series, current[0])
    if not previous:
        return None

    current_date, last = current
    _, prev = previous
    change = last - prev
    change_pct = (change / prev) * 100 if prev else 0.0

    return {
        "Name": item["name"],
        "Symbol": symbol,
        "Date": current_date.isoformat(),
        "Last": round(last, 4),
        "Previous": round(prev, 4),
        "Change": round(change, 4),
        "ChangePct": round(change_pct, 4),
        "ChangeStyle": item.get("changeStyle", "pct"),
    }


def get_label(name: str) -> str:
    return LABELS_ZH.get(name, name)


def tone_text(index_rows: list[dict]) -> str:
    moves = [row["ChangePct"] for row in index_rows]
    if not moves:
        return "主要指數缺少資料"

    positive_count = sum(1 for move in moves if move > 0)
    negative_count = sum(1 for move in moves if move < 0)
    average = sum(moves) / len(moves)

    if positive_count == len(moves):
        if average >= 1:
            return "四大指數全面走強"
        if average >= 0.3:
            return "主要指數普遍收高"
        return "主要指數小幅上揚"

    if negative_count == len(moves):
        if average <= -1:
            return "四大指數全面走弱"
        if average <= -0.3:
            return "主要指數普遍收低"
        return "主要指數小幅回落"

    return "主要指數漲跌互見"


def summary_line_us(index_rows: list[dict], sector_rows: list[dict], macro_rows: list[dict]) -> str:
    tone = tone_text(index_rows)
    top_sector = max(sector_rows, key=lambda row: row["ChangePct"])
    bottom_sector = min(sector_rows, key=lambda row: row["ChangePct"])
    ten_year = next((row for row in macro_rows if row["Name"] == "US 10Y Treasury"), None)
    vix = next((row for row in macro_rows if row["Name"] == "VIX"), None)

    if ten_year and ten_year["Change"] > 0:
        rate_text = "美國 10 年期公債殖利率走高"
    elif ten_year and ten_year["Change"] < 0:
        rate_text = "美國 10 年期公債殖利率回落"
    else:
        rate_text = "美國 10 年期公債殖利率大致持平"

    if vix and vix["Change"] > 0:
        vix_text = "市場波動升溫"
    elif vix and vix["Change"] < 0:
        vix_text = "市場波動降溫"
    else:
        vix_text = "市場波動大致持平"

    return (
        f"{tone}，類股以{get_label(top_sector['Name'])}領漲、"
        f"{get_label(bottom_sector['Name'])}相對承壓；{rate_text}，{vix_text}。"
    )


def summary_line_europe(index_rows: list[dict]) -> str:
    positive = [row for row in index_rows if row["ChangePct"] > 0]
    negative = [row for row in index_rows if row["ChangePct"] < 0]
    leader = max(index_rows, key=lambda row: row["ChangePct"])
    laggard = min(index_rows, key=lambda row: row["ChangePct"])

    if positive and negative:
        tone = "歐股三大指數漲跌互見"
    elif positive:
        tone = "歐股三大指數全面走高"
    else:
        tone = "歐股三大指數全面走低"

    return f"{tone}，{get_label(leader['Name'])}表現相對較強，{get_label(laggard['Name'])}相對承壓。"


def format_signed(value: float, decimals: int = 2) -> str:
    return f"{value:+.{decimals}f}"


def format_last_value(row: dict) -> str:
    if row["ChangeStyle"] == "bps":
        return f"{row['Last']:.3f}%"
    return f"{row['Last']:.2f}"


def format_change_text(row: dict) -> str:
    style = row["ChangeStyle"]
    if style == "abs":
        return format_signed(row["Change"])
    if style == "bps":
        return f"{format_signed(row['Change'] * 100)} bp"
    return f"{format_signed(row['ChangePct'])}%"


def ranked_summary(rows: list[dict]) -> str:
    return "、".join(f"{get_label(row['Name'])} {format_change_text(row)}" for row in rows)


def display_lines(title: str, rows: list[dict]) -> list[str]:
    lines = [f"## {title}"]
    for row in rows:
        lines.append(f"- {get_label(row['Name'])}：{format_last_value(row)}（{format_change_text(row)}）")
    return lines


def build_us_payload(market_config: dict, series_by_symbol: dict[str, list[tuple[dt.date, float]]], summary_date: dt.date) -> tuple[dict, list[str]]:
    index_rows = [build_row(item, series_by_symbol, summary_date) for item in market_config["indices"]]
    macro_rows = [build_row(item, series_by_symbol, summary_date) for item in market_config.get("macro", [])]
    sector_rows = [build_row(item, series_by_symbol, summary_date) for item in market_config.get("sectors", [])]
    megacap_rows = [build_row(item, series_by_symbol, summary_date) for item in market_config.get("megacaps", [])]

    index_rows = [row for row in index_rows if row]
    macro_rows = [row for row in macro_rows if row]
    sector_rows = [row for row in sector_rows if row]
    megacap_rows = [row for row in megacap_rows if row]

    top_sectors = sorted(sector_rows, key=lambda row: row["ChangePct"], reverse=True)[:3]
    weakest_sectors = sorted(sector_rows, key=lambda row: row["ChangePct"])[:3]
    megacap_leaders = sorted(megacap_rows, key=lambda row: row["ChangePct"], reverse=True)[:3]
    megacap_laggards = sorted(megacap_rows, key=lambda row: row["ChangePct"])[:3]

    headline = summary_line_us(index_rows, sector_rows, macro_rows)
    display_date = summary_date.isoformat()
    display_date_zh = f"{summary_date.year}年{summary_date.month:02d}月{summary_date.day:02d}日"

    lines = [
        f"# {market_config['reportTitle']} | {display_date}",
        "",
        f"副標：{display_date_zh} {market_config['subtitleSuffix']}",
        "",
        "## 盤勢摘要",
        headline,
        f"- 最強族群：{ranked_summary(top_sectors)}",
        f"- 最弱族群：{ranked_summary(weakest_sectors)}",
        f"- 大型股強勢股：{ranked_summary(megacap_leaders)}",
        f"- 大型股弱勢股：{ranked_summary(megacap_laggards)}",
        "",
    ]
    for section_title, rows in [
        ("主要指數", index_rows),
        ("跨資產觀察", macro_rows),
        ("領漲類股", top_sectors),
        ("領跌類股", weakest_sectors),
        ("大型股強勢名單", megacap_leaders),
        ("大型股弱勢名單", megacap_laggards),
    ]:
        lines.extend(display_lines(section_title, rows))
        lines.append("")

    payload = {
        "summaryDate": display_date,
        "priceSource": "Yahoo Finance",
        "oneLineSummary": headline,
        "indices": index_rows,
        "macro": macro_rows,
        "topSectors": top_sectors,
        "weakestSectors": weakest_sectors,
        "megacapLeaders": megacap_leaders,
        "megacapLaggards": megacap_laggards,
    }
    return payload, lines


def build_europe_payload(market_config: dict, series_by_symbol: dict[str, list[tuple[dt.date, float]]], summary_date: dt.date) -> tuple[dict, list[str]]:
    index_rows = [build_row(item, series_by_symbol, summary_date) for item in market_config["indices"]]
    index_rows = [row for row in index_rows if row]

    headline = summary_line_europe(index_rows)
    display_date = summary_date.isoformat()
    display_date_zh = f"{summary_date.year}年{summary_date.month:02d}月{summary_date.day:02d}日"

    lines = [
        f"# {market_config['reportTitle']} | {display_date}",
        "",
        f"副標：{display_date_zh} {market_config['subtitleSuffix']}",
        "",
        "## 盤勢摘要",
        headline,
        "",
    ]
    lines.extend(display_lines("主要指數", index_rows))
    lines.append("")

    payload = {
        "summaryDate": display_date,
        "priceSource": "Yahoo Finance",
        "oneLineSummary": headline,
        "indices": index_rows,
    }
    return payload, lines


def write_outputs(output_dir: pathlib.Path, stem: str, display_date: str, payload: dict, lines: list[str]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    dated_markdown = output_dir / f"{display_date}_{stem}.md"
    latest_markdown = output_dir / f"latest_{stem}.md"
    dated_json = output_dir / f"{display_date}_{stem}.json"
    latest_json = output_dir / f"latest_{stem}.json"

    text = "\n".join(lines).rstrip() + "\n"
    dated_markdown.write_text(text, encoding="utf-8")
    latest_markdown.write_text(text, encoding="utf-8")
    json_text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    dated_json.write_text(json_text, encoding="utf-8")
    latest_json.write_text(json_text, encoding="utf-8")


def run_market(market_config: dict, as_of_date: dt.date, output_dir: pathlib.Path) -> tuple[str, str]:
    items: list[dict] = []
    items.extend(market_config.get("indices", []))
    items.extend(market_config.get("macro", []))
    items.extend(market_config.get("sectors", []))
    items.extend(market_config.get("megacaps", []))

    start = as_of_date - dt.timedelta(days=15)
    series_by_symbol: dict[str, list[tuple[dt.date, float]]] = {}
    for item in items:
        symbol = item["symbol"]
        if symbol in series_by_symbol:
            continue
        series_by_symbol[symbol] = fetch_series(symbol, start, as_of_date, item.get("priceScale", 1.0))

    summary_series = series_by_symbol[market_config["summarySymbol"]]
    summary_point = get_point_on_or_before(summary_series, as_of_date)
    if not summary_point:
        raise RuntimeError(f"Unable to determine summary date for {market_config['key']}.")
    summary_date = summary_point[0]

    if market_config["key"] == "us":
        payload, lines = build_us_payload(market_config, series_by_symbol, summary_date)
    else:
        payload, lines = build_europe_payload(market_config, series_by_symbol, summary_date)

    write_outputs(output_dir, market_config["outputStem"], summary_date.isoformat(), payload, lines)
    return summary_date.isoformat(), market_config["outputStem"]


def main() -> None:
    args = parse_args()
    config = load_config(pathlib.Path(args.config_path))
    output_dir = pathlib.Path(args.output_dir)
    as_of_date = parse_as_of_date(args.as_of_date)

    markets = config["markets"]
    if args.market != "all":
        markets = [market for market in markets if market["key"] == args.market]

    if not markets:
        raise RuntimeError("No market configuration selected.")

    for market in markets:
        display_date, stem = run_market(market, as_of_date, output_dir)
        print(f"Generated {stem} for {display_date}")


if __name__ == "__main__":
    main()
