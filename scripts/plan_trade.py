#!/usr/bin/env python3
"""Calculate a long-position risk plan without broker or market-data access."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Iterable


def _require_finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} 必须是有限数字")


def plan_trade(
    equity: float,
    risk_pct: float,
    entry: float,
    stop: float,
    target: float | None = None,
    max_position_pct: float = 20.0,
    lot_size: int = 1,
) -> dict:
    """Size a long trade by account risk, then apply position and lot caps."""
    numeric = {
        "equity": equity,
        "risk_pct": risk_pct,
        "entry": entry,
        "stop": stop,
        "max_position_pct": max_position_pct,
    }
    if target is not None:
        numeric["target"] = target
    for name, value in numeric.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} 必须是数字")
        _require_finite(name, float(value))

    if equity <= 0:
        raise ValueError("equity 必须大于 0")
    if not 0 < risk_pct <= 100:
        raise ValueError("risk_pct 必须在 0–100 之间且不能为 0")
    if entry <= 0 or stop <= 0:
        raise ValueError("entry 和 stop 必须大于 0")
    if entry <= stop:
        raise ValueError("多头交易要求 entry > stop")
    if target is not None and target <= entry:
        raise ValueError("多头交易要求 target > entry")
    if not 0 < max_position_pct <= 100:
        raise ValueError("max_position_pct 必须在 0–100 之间且不能为 0")
    if not isinstance(lot_size, int) or isinstance(lot_size, bool) or lot_size < 1:
        raise ValueError("lot_size 必须是正整数")

    risk_budget = equity * risk_pct / 100
    risk_per_share = entry - stop
    risk_based_shares = math.floor(risk_budget / risk_per_share)
    position_budget = equity * max_position_pct / 100
    position_cap_shares = math.floor(position_budget / entry)
    uncapped_shares = min(risk_based_shares, position_cap_shares)
    shares = (uncapped_shares // lot_size) * lot_size
    limiting_constraint = "account_risk" if risk_based_shares <= position_cap_shares else "position_cap"
    notional = shares * entry
    planned_risk = shares * risk_per_share
    warnings = []
    if shares == 0:
        warnings.append("按风险、仓位和手数约束计算后不足一手，不建仓")
    if risk_based_shares > position_cap_shares:
        warnings.append("单股仓位上限使实际风险低于风险预算")

    return {
        "method": "engineering-assumption-v1; not a JLaw position-sizing rule",
        "inputs": {
            "equity": equity,
            "risk_pct": risk_pct,
            "entry": entry,
            "stop": stop,
            "target": target,
            "max_position_pct": max_position_pct,
            "lot_size": lot_size,
        },
        "risk_budget": risk_budget,
        "risk_per_share": risk_per_share,
        "stop_distance_pct": risk_per_share / entry * 100,
        "risk_based_shares_before_caps": risk_based_shares,
        "position_cap_shares_before_lot": position_cap_shares,
        "shares": shares,
        "notional": notional,
        "position_pct": notional / equity * 100,
        "planned_risk": planned_risk,
        "actual_risk_pct": planned_risk / equity * 100,
        "limiting_constraint": limiting_constraint,
        "target_r": None if target is None else (target - entry) / risk_per_share,
        "warnings": warnings,
        "disclaimer": "未计佣金、费用、滑点、跳空和流动性冲击；实际亏损可能超过计划风险。",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="多头交易风险与仓位计算")
    parser.add_argument("--equity", type=float, required=True, help="账户净值")
    parser.add_argument("--risk-pct", type=float, required=True, help="账户风险预算百分比")
    parser.add_argument("--entry", type=float, required=True, help="计划入场价")
    parser.add_argument("--stop", type=float, required=True, help="初始止损价")
    parser.add_argument("--target", type=float, help="可选目标价")
    parser.add_argument(
        "--max-position-pct", type=float, default=20.0, help="单股名义仓位上限，默认 20%%"
    )
    parser.add_argument("--lot-size", type=int, default=1, help="最小交易手数，默认 1 股")
    parser.add_argument("--output", help="可选 JSON 输出路径；默认打印到标准输出")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = plan_trade(
            equity=args.equity,
            risk_pct=args.risk_pct,
            entry=args.entry,
            stop=args.stop,
            target=args.target,
            max_position_pct=args.max_position_pct,
            lot_size=args.lot_size,
        )
    except ValueError as exc:
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
