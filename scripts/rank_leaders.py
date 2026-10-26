#!/usr/bin/env python3
"""Rank price-leadership candidates within one theme using only stdlib."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Iterable

REQUIRED_PRICE_COLUMNS = {
    "theme",
    "symbol",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
}
WEIGHTS = {
    "return_60d": 0.30,
    "return_20d": 0.20,
    "down_day_resilience": 0.20,
    "high_proximity_60d": 0.15,
    "trend_quality": 0.15,
}
MIN_HISTORY = 220


def _finite_number(value: str, field: str, line_number: int) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"第 {line_number} 行的 {field} 不是数字") from exc
    if not math.isfinite(number):
        raise ValueError(f"第 {line_number} 行的 {field} 必须是有限数字")
    return number


def load_prices(prices_path: str | Path, theme: str) -> tuple[dict[str, list[dict]], str]:
    """Load and validate one theme, returning rows by symbol and the cutoff date."""
    rows_by_symbol: dict[str, list[dict]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    latest = None

    with Path(prices_path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_PRICE_COLUMNS.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"prices.csv 缺少字段：{', '.join(sorted(missing))}")

        for line_number, raw in enumerate(reader, start=2):
            if raw["theme"] != theme:
                continue
            symbol = (raw["symbol"] or "").strip()
            if not symbol:
                raise ValueError(f"第 {line_number} 行的 symbol 为空")
            try:
                trading_date = date.fromisoformat(raw["date"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"第 {line_number} 行的 date 必须为 YYYY-MM-DD") from exc

            key = (symbol, raw["date"])
            if key in seen:
                raise ValueError(f"检测到重复记录：{symbol} {raw['date']}")
            seen.add(key)

            values = {
                field: _finite_number(raw[field], field, line_number)
                for field in ("open", "high", "low", "close", "volume")
            }
            if min(values["open"], values["high"], values["low"], values["close"]) <= 0:
                raise ValueError(f"第 {line_number} 行的 OHLC 必须大于 0")
            if values["volume"] < 0:
                raise ValueError(f"第 {line_number} 行的 volume 不能为负数")
            if values["high"] < max(values["open"], values["close"], values["low"]):
                raise ValueError(f"第 {line_number} 行的 high 与 OHLC 不一致")
            if values["low"] > min(values["open"], values["close"], values["high"]):
                raise ValueError(f"第 {line_number} 行的 low 与 OHLC 不一致")

            row = {"symbol": symbol, "date": raw["date"], **values}
            rows_by_symbol[symbol].append(row)
            latest = raw["date"] if latest is None else max(latest, raw["date"])

    if not rows_by_symbol or latest is None:
        raise ValueError(f"没有找到题材 {theme!r} 的行情记录")
    for rows in rows_by_symbol.values():
        rows.sort(key=lambda row: row["date"])
    return dict(rows_by_symbol), latest


def load_metadata(metadata_path: str | Path | None) -> dict[str, dict]:
    if metadata_path is None:
        return {}
    metadata = {}
    with Path(metadata_path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = {"symbol", "relevance"}.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"relevance.csv 缺少字段：{', '.join(sorted(missing))}")
        for line_number, row in enumerate(reader, start=2):
            symbol = (row["symbol"] or "").strip()
            if not symbol or symbol in metadata:
                raise ValueError(f"第 {line_number} 行的 symbol 为空或重复")
            relevance = _finite_number(row["relevance"], "relevance", line_number)
            if not 0 <= relevance <= 100:
                raise ValueError(f"第 {line_number} 行的 relevance 必须在 0–100")
            metadata[symbol] = {
                "name": (row.get("name") or "").strip(),
                "relevance": relevance,
                "note": (row.get("note") or "").strip(),
            }
    return metadata


def _percentiles(values: dict[str, float]) -> dict[str, float]:
    """Ascending average-rank percentiles; higher raw values score higher."""
    count = len(values)
    if count == 1:
        return {next(iter(values)): 50.0}

    ordered = sorted(values, key=values.__getitem__)
    result = {}
    start = 0
    while start < count:
        end = start + 1
        while end < count and values[ordered[end]] == values[ordered[start]]:
            end += 1
        average_rank = ((start + 1) + end) / 2
        percentile = 100 * (average_rank - 1) / (count - 1)
        for index in range(start, end):
            result[ordered[index]] = percentile
        start = end
    return result


def _theme_down_days(eligible: dict[str, dict]) -> set[str]:
    returns_by_date: dict[str, list[float]] = defaultdict(list)
    for item in eligible.values():
        for row_date, stock_return in item["daily_returns"].items():
            returns_by_date[row_date].append(stock_return)

    dates = sorted(returns_by_date)[-60:]
    down_days = set()
    for row_date in dates:
        theme_return = sum(returns_by_date[row_date]) / len(returns_by_date[row_date])
        if theme_return < 0:
            down_days.add(row_date)
    return down_days


def rank_leaders(
    prices_path: str | Path,
    theme: str,
    min_dollar_volume: float = 2_000_000,
    trend_gate: bool = True,
    metadata_path: str | Path | None = None,
    top: int = 10,
) -> dict:
    """Return an explainable cross-sectional ranking and all exclusions."""
    if not math.isfinite(min_dollar_volume) or min_dollar_volume < 0:
        raise ValueError("min_dollar_volume 必须是不小于 0 的有限数字")
    if not isinstance(top, int) or isinstance(top, bool) or top < 1:
        raise ValueError("top 必须是正整数")

    rows_by_symbol, as_of = load_prices(prices_path, theme)
    metadata = load_metadata(metadata_path)
    eligible: dict[str, dict] = {}
    excluded = []

    for symbol, rows in sorted(rows_by_symbol.items()):
        reasons = []
        if len(rows) < MIN_HISTORY:
            reasons.append(f"历史数据不足 {MIN_HISTORY} 根日 K（实际 {len(rows)}）")
        if rows[-1]["date"] != as_of:
            reasons.append(f"最新日期 {rows[-1]['date']} 早于题材截止日 {as_of}")
        if reasons:
            excluded.append({"symbol": symbol, "reasons": reasons})
            continue

        closes = [row["close"] for row in rows]
        sma50 = sum(closes[-50:]) / 50
        sma200 = sum(closes[-200:]) / 200
        sma200_20d_ago = sum(closes[-220:-20]) / 200
        median_dollar_volume = statistics.median(
            row["close"] * row["volume"] for row in rows[-20:]
        )

        if trend_gate:
            if not closes[-1] > sma50:
                reasons.append("收盘价未高于 50 日均线")
            if not sma50 > sma200:
                reasons.append("50 日均线未高于 200 日均线")
            if not sma200 > sma200_20d_ago:
                reasons.append("200 日均线未高于 20 个交易日前")
        if median_dollar_volume < min_dollar_volume:
            reasons.append(
                f"20 日成交额中位数 {median_dollar_volume:.2f} 低于门槛 {min_dollar_volume:.2f}"
            )
        if reasons:
            excluded.append({"symbol": symbol, "reasons": reasons})
            continue

        daily_returns = {
            rows[index]["date"]: closes[index] / closes[index - 1] - 1
            for index in range(len(rows) - 60, len(rows))
        }
        eligible[symbol] = {
            "daily_returns": daily_returns,
            "metrics": {
                "return_60d": closes[-1] / closes[-61] - 1,
                "return_20d": closes[-1] / closes[-21] - 1,
                "high_proximity_60d": closes[-1] / max(closes[-60:]),
                "trend_quality": (
                    (closes[-1] / sma50 - 1)
                    + (sma50 / sma200 - 1)
                    + (sma200 / sma200_20d_ago - 1)
                )
                / 3,
            },
            "close": closes[-1],
            "sma50": sma50,
            "sma200": sma200,
            "sma200_20d_ago": sma200_20d_ago,
            "median_dollar_volume_20d": median_dollar_volume,
        }

    warnings = []
    down_days = _theme_down_days(eligible)
    if eligible and not down_days:
        warnings.append("观察窗口内没有主题下跌日，下跌日韧性统一记为 0，不具区分度")

    component_values = {name: {} for name in WEIGHTS}
    for symbol, item in eligible.items():
        metrics = item["metrics"]
        metrics["down_day_resilience"] = sum(
            item["daily_returns"].get(row_date, 0.0) for row_date in down_days
        )
        for name in WEIGHTS:
            component_values[name][symbol] = metrics[name]

    component_percentiles = {
        name: _percentiles(values) for name, values in component_values.items()
    }
    candidates = []
    for symbol, item in eligible.items():
        percentiles = {
            name: component_percentiles[name][symbol] for name in WEIGHTS
        }
        score = sum(WEIGHTS[name] * percentiles[name] for name in WEIGHTS)
        candidate = {
            "symbol": symbol,
            "score": score,
            "metrics": item["metrics"],
            "component_percentiles": percentiles,
            "close": item["close"],
            "sma50": item["sma50"],
            "sma200": item["sma200"],
            "sma200_slope_20d": item["sma200"] / item["sma200_20d_ago"] - 1,
            "median_dollar_volume_20d": item["median_dollar_volume_20d"],
        }
        if symbol in metadata:
            candidate["relevance_evidence"] = metadata[symbol]
        candidates.append(candidate)

    candidates.sort(key=lambda item: (-item["score"], item["symbol"]))
    for rank, candidate in enumerate(candidates, start=1):
        candidate["rank"] = rank

    if metadata_path is None:
        warnings.append("未提供 relevance.csv：结果仅为价格领导力候选，题材相关性尚未核验")
        result_label = "价格领导力候选"
    else:
        result_label = "价格领导力排名（相关性标签由使用者提供，未计入评分）"
        missing_metadata = sorted(set(eligible).difference(metadata))
        if missing_metadata:
            warnings.append(f"以下候选缺少相关性标签：{', '.join(missing_metadata)}")

    return {
        "method": "engineering-assumption-v1; not a JLaw formula",
        "theme": theme,
        "as_of": as_of,
        "result_label": result_label,
        "parameters": {
            "min_history": MIN_HISTORY,
            "min_dollar_volume": min_dollar_volume,
            "trend_gate": trend_gate,
            "top": top,
            "weights": WEIGHTS,
            "theme_return_window": 60,
            "theme_return_construction": "eligible symbols, equal-weight daily returns",
            "resilience_construction": "sum of stock daily returns on negative-theme days",
        },
        "eligible_count": len(candidates),
        "candidates": candidates[:top],
        "excluded": excluded,
        "warnings": warnings,
        "disclaimer": "排名不是买入信号；不包含交易成本、跳空、流动性冲击或个性化投资建议。",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="题材内价格领导力候选排名")
    parser.add_argument("--prices", required=True, help="长表 OHLCV CSV")
    parser.add_argument("--theme", required=True, help="要分析的题材名称")
    parser.add_argument("--metadata", help="可选的人工相关性标签 CSV")
    parser.add_argument("--top", type=int, default=10, help="输出前 N 名，默认 10")
    parser.add_argument(
        "--min-dollar-volume",
        type=float,
        default=2_000_000,
        help="20 日成交额中位数门槛，默认 2000000",
    )
    parser.add_argument("--no-trend-gate", action="store_true", help="关闭趋势门槛用于对照")
    parser.add_argument("--output", help="可选 JSON 输出路径；默认打印到标准输出")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = rank_leaders(
            prices_path=args.prices,
            theme=args.theme,
            min_dollar_volume=args.min_dollar_volume,
            trend_gate=not args.no_trend_gate,
            metadata_path=args.metadata,
            top=args.top,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(f"错误：{exc}") from exc

    text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
