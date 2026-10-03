#!/usr/bin/env python3
"""Frozen numeric validator for W7017-DIR-016 completed-hour wick prior.

The validator preserves the exact P0-A event universe, builds only the
immediately preceding fully completed UTC-hour candle from hash-pinned local
OKX one-minute bars, fits calibration-only quintile direction tables, freezes
actions, and evaluates the reused historical post-cutoff block.

No detector/event rebuild, market download, parameter search, outcome refit, or
promotion claim is allowed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = ROOT / "data/direction_event_ledger/p0a_ohlcv"
DEFAULT_BTC_BARS = ROOT / "data/okx_swap_multi/BTC-USDT-SWAP_1m.parquet"
DEFAULT_ETH_BARS = ROOT / "data/okx_swap_multi/ETH-USDT-SWAP_1m.parquet"
DEFAULT_OUT = ROOT / "research/W7017_DIR016_NUMERIC_DIRECTION_VALIDATION_WORKER5300_20260927.json"

EXPECTED_ROWS = 1147
EXPECTED_ASSET_COUNTS = {"BTC": 535, "ETH": 612}
EXPECTED_P0A_SHA = {
    "direction_event_core.parquet": "13bbd824115d023cdc8c98a3aa596c70d1e037af779d3c314dc76f6ea3bc41ad",
    "direction_outcome.parquet": "6e97adaeaa6605bdebc8d0a39c44f8cc42aa9be5bc85b009c71229098b75e3d9",
}
EXPECTED_RAW_SHA = {
    "BTC": "34fc490ff3df8bdf0d70d102d2acbe6576876353ce7c125ab623ce195ee31abc",
    "ETH": "6d090908df785ba77e85256bc324354fe6716823908306bedfa1ad1851c46809",
}

CUTOFF = pd.Timestamp("2025-07-01T00:00:00Z")
HORIZON_MIN = 240
PRIMARY_COST_BP = 20.0
STRESS_COST_BP = 30.0
EV_SEPARATION_BP = 5.0
MIN_CELL_N = 30
MIN_UP_N = 10
MIN_NONUP_N = 10
MIN_EVAL_N = 100
MIN_ACTIVE_DAYS = 50
MIN_SUBGROUP_N = 30
BOOTSTRAP_DRAWS = 5000
BOOTSTRAP_SEED = 7017026
RANDOM_DRAWS = 10000
RANDOM_SEED = 7017016
DIRECTION_WILSON_Z = 1.6448536269514722
CRYPTO_FAVORABLE_VERDICT = "RETROSPECTIVE_REFERENCE_SUPPORT_ONLY__PROSPECTIVE_CONFIRMATION_REQUIRED"
CROSS_MARKET_UNTESTED_VERDICT = (
    "INDETERMINATE_CROSS_MARKET_NOT_TESTED__"
    "CRYPTO_DIAGNOSTIC_PASS__MECHANISM_NOT_REJECTED__NO_PROMOTION"
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ledger-root", type=Path, default=DEFAULT_LEDGER)
    p.add_argument("--btc-bars", type=Path, default=DEFAULT_BTC_BARS)
    p.add_argument("--eth-bars", type=Path, default=DEFAULT_ETH_BARS)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return p.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def exact_order_stat(values: np.ndarray, one_based_rank: int) -> float:
    clean = np.asarray(values, dtype=float)
    clean = clean[np.isfinite(clean)]
    if len(clean) == 0:
        return math.nan
    if one_based_rank < 1 or one_based_rank > len(clean):
        raise ValueError("order-stat rank out of bounds")
    return float(np.sort(clean)[one_based_rank - 1])


def quantile_bounds(values: pd.Series) -> np.ndarray:
    clean = pd.to_numeric(values, errors="coerce").dropna().to_numpy(float)
    if len(clean) == 0:
        raise ValueError("cannot fit quantiles on empty feature")
    return np.quantile(clean, [0.2, 0.4, 0.6, 0.8], method="linear").astype(float)


def assign_quintile(value: float, bounds: np.ndarray) -> int | None:
    if not math.isfinite(float(value)):
        return None
    b = np.asarray(bounds, dtype=float)
    if b.shape != (4,) or not np.isfinite(b).all():
        raise ValueError("invalid quintile boundaries")
    return int(np.searchsorted(b, float(value), side="left") + 1)


def normalize_bars(frame: pd.DataFrame) -> pd.DataFrame:
    needed = ["open", "high", "low", "close"]
    missing = [c for c in needed if c not in frame.columns]
    if missing:
        raise ValueError(f"bar frame missing columns: {missing}")
    out = frame[needed].copy()
    idx = pd.to_datetime(out.index, utc=True, errors="coerce")
    if idx.isna().any():
        raise ValueError("bar index contains invalid timestamps")
    out.index = pd.DatetimeIndex(idx)
    return out.sort_index(kind="stable")


def read_bars(path: Path) -> pd.DataFrame:
    return normalize_bars(pd.read_parquet(path, columns=["open", "high", "low", "close"]))


def prior_hour_feature(decision_ts: object, bars: pd.DataFrame) -> dict[str, Any]:
    decision = pd.Timestamp(decision_ts)
    decision = decision.tz_localize("UTC") if decision.tzinfo is None else decision.tz_convert("UTC")
    current_hour_start = decision.floor("h")
    hour_start = current_hour_start - pd.Timedelta(hours=1)
    hour_end = current_hour_start - pd.Timedelta(minutes=1)
    expected = pd.date_range(hour_start, hour_end, freq="1min", tz="UTC")

    part = bars.loc[(bars.index >= hour_start) & (bars.index <= hour_end), ["open", "high", "low", "close"]].copy()
    base = {
        "feature_known": False,
        "missing_reason": None,
        "source_hour_start_utc": hour_start,
        "source_hour_end_utc": hour_end,
        "valid_minutes": 0,
        "hour_open": math.nan,
        "hour_high": math.nan,
        "hour_low": math.nan,
        "hour_close": math.nan,
        "upper_wick": math.nan,
        "lower_wick": math.nan,
        "epsilon_price": math.nan,
        "wick_skew": math.nan,
    }

    if len(part) != 60:
        base["missing_reason"] = "MINUTE_COUNT_NOT_60"
        base["valid_minutes"] = int(len(part))
        return base
    if part.index.duplicated(keep=False).any():
        base["missing_reason"] = "DUPLICATE_MINUTE"
        return base
    if not part.index.equals(expected):
        base["missing_reason"] = "NONCONTIGUOUS_OR_MISALIGNED_MINUTES"
        return base

    values = part.to_numpy(dtype=float)
    finite = np.isfinite(values).all(axis=1)
    positive = (values > 0).all(axis=1)
    valid_ohlc = (
        (part["high"].to_numpy(float) >= np.maximum(part["open"].to_numpy(float), part["close"].to_numpy(float)))
        & (np.minimum(part["open"].to_numpy(float), part["close"].to_numpy(float)) >= part["low"].to_numpy(float))
    )
    base["valid_minutes"] = int((finite & positive & valid_ohlc).sum())
    if not (finite & positive & valid_ohlc).all():
        base["missing_reason"] = "INVALID_OHLC"
        return base

    o = float(part["open"].iloc[0])
    h = float(part["high"].max())
    l = float(part["low"].min())
    c = float(part["close"].iloc[-1])
    upper = float(h - max(o, c))
    lower = float(min(o, c) - l)
    eps = float(max(1e-12, abs(c) * 1e-12))
    denom = float(max(h - l, eps))
    skew = float((upper - lower) / denom)

    base.update(
        {
            "feature_known": True,
            "valid_minutes": 60,
            "hour_open": o,
            "hour_high": h,
            "hour_low": l,
            "hour_close": c,
            "upper_wick": upper,
            "lower_wick": lower,
            "epsilon_price": eps,
            "wick_skew": skew,
        }
    )
    return base


def build_feature_table(core: pd.DataFrame, bars_by_asset: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for event in core.itertuples(index=False):
        asset = str(event.asset).upper()
        if asset not in bars_by_asset:
            raise ValueError(f"missing raw bars for asset {asset}")
        feature = prior_hour_feature(event.decision_ts_utc, bars_by_asset[asset])
        rows.append(
            {
                "event_id": str(event.event_id),
                "asset": asset,
                "decision_ts_utc": pd.Timestamp(event.decision_ts_utc),
                **feature,
            }
        )
    out = pd.DataFrame(rows)
    if len(out) != len(core) or out["event_id"].duplicated().any():
        raise RuntimeError("feature construction changed event identity")
    return out


def outcome_magnitudes(values: pd.Series) -> dict[str, float | int]:
    r = pd.to_numeric(values, errors="coerce").dropna().to_numpy(float)
    up = r > 0
    nonup = r <= 0
    return {
        "n": int(len(r)),
        "up_n": int(up.sum()),
        "nonup_n": int(nonup.sum()),
        "p_up": float(up.mean()) if len(r) else math.nan,
        "m_up_bp": float(r[up].mean()) if up.any() else 0.0,
        "m_down_bp": float((-r[nonup]).mean()) if nonup.any() else 0.0,
    }


def fit_calibration_model(calibration: pd.DataFrame) -> dict[str, Any]:
    model: dict[str, Any] = {"assets": {}}
    for asset in ("BTC", "ETH"):
        part = calibration[calibration["asset"].eq(asset)].copy()
        bounds = quantile_bounds(part["wick_skew"])
        part["wick_quintile"] = [assign_quintile(x, bounds) for x in part["wick_skew"]]
        unconditional = outcome_magnitudes(part["gross_return_bp"])
        cells: dict[int, dict[str, Any]] = {}
        for q in range(1, 6):
            qpart = part[part["wick_quintile"].eq(q)]
            stats = outcome_magnitudes(qpart["gross_return_bp"])
            p = float(stats["p_up"]) if stats["n"] else math.nan
            m_up = float(stats["m_up_bp"])
            m_down = float(stats["m_down_bp"])
            long_ev = p * m_up - (1.0 - p) * m_down - PRIMARY_COST_BP if math.isfinite(p) else math.nan
            short_ev = (1.0 - p) * m_down - p * m_up - PRIMARY_COST_BP if math.isfinite(p) else math.nan
            supported = bool(
                stats["n"] >= MIN_CELL_N
                and stats["up_n"] >= MIN_UP_N
                and stats["nonup_n"] >= MIN_NONUP_N
            )
            side = 0
            if supported and long_ev > 0 and long_ev - short_ev > EV_SEPARATION_BP:
                side = 1
            elif supported and short_ev > 0 and short_ev - long_ev > EV_SEPARATION_BP:
                side = -1
            cells[q] = {
                **stats,
                "support_gate_pass": supported,
                "long_ev_20bp": long_ev,
                "short_ev_20bp": short_ev,
                "chosen_side": int(side),
                "chosen_side_label": "LONG" if side > 0 else ("SHORT" if side < 0 else "HOLD"),
            }
        model["assets"][asset] = {
            "quintile_bounds": bounds.tolist(),
            "unconditional": unconditional,
            "cells": cells,
        }
    return model


def apply_frozen_model(evaluation: pd.DataFrame, model: dict[str, Any]) -> pd.DataFrame:
    out = evaluation.copy()
    quintiles: list[int | None] = []
    sides: list[int] = []
    p0s: list[float] = []
    p1s: list[float] = []
    for row in out.itertuples(index=False):
        asset_model = model["assets"].get(str(row.asset))
        if not asset_model or not bool(row.feature_known):
            quintiles.append(None)
            sides.append(0)
            p0s.append(math.nan)
            p1s.append(math.nan)
            continue
        q = assign_quintile(float(row.wick_skew), np.asarray(asset_model["quintile_bounds"], dtype=float))
        cell = asset_model["cells"].get(q)
        quintiles.append(q)
        sides.append(int(cell["chosen_side"]) if cell else 0)
        p0s.append(float(asset_model["unconditional"]["p_up"]))
        p1s.append(float(cell["p_up"]) if cell else math.nan)
    out["wick_quintile"] = quintiles
    out["action_side"] = sides
    out["m0_p_up"] = p0s
    out["m1_p_up"] = p1s
    return out


def probability_comparator(evaluation: pd.DataFrame) -> dict[str, Any]:
    y = (pd.to_numeric(evaluation["gross_return_bp"], errors="coerce") > 0).astype(float)
    p0 = pd.to_numeric(evaluation["m0_p_up"], errors="coerce")
    p1 = pd.to_numeric(evaluation["m1_p_up"], errors="coerce")
    mask = evaluation["feature_known"].astype(bool) & y.notna() & p0.notna() & p1.notna()
    if not mask.any():
        return {
            "n": 0,
            "m0_brier": math.nan,
            "m1_brier": math.nan,
            "m0_logloss": math.nan,
            "m1_logloss": math.nan,
            "m1_incremental_pass": False,
        }
    yy = y[mask].to_numpy(float)
    a = p0[mask].to_numpy(float)
    b = p1[mask].to_numpy(float)

    def brier(p: np.ndarray) -> float:
        return float(np.mean((p - yy) ** 2))

    def logloss(p: np.ndarray) -> float:
        q = np.clip(p, 1e-6, 1 - 1e-6)
        return float(-np.mean(yy * np.log(q) + (1 - yy) * np.log(1 - q)))

    b0, b1, l0, l1 = brier(a), brier(b), logloss(a), logloss(b)
    return {
        "n": int(len(yy)),
        "m0_brier": b0,
        "m1_brier": b1,
        "m0_logloss": l0,
        "m1_logloss": l1,
        "m1_incremental_pass": bool(b1 <= b0 and l1 <= l0 and (b1 < b0 or l1 < l0)),
    }


def mde(values: np.ndarray, z: float = 1.96) -> float:
    clean = np.asarray(values, dtype=float)
    clean = clean[np.isfinite(clean)]
    if len(clean) < 2:
        return math.nan
    return float(z * np.std(clean, ddof=1) / math.sqrt(len(clean)))


def wilson_lower_bound(
    successes: int,
    total: int,
    *,
    z: float = DIRECTION_WILSON_Z,
) -> float:
    """One-sided Wilson lower confidence bound for a Bernoulli hit rate."""
    if total <= 0 or successes < 0 or successes > total:
        return math.nan
    p = float(successes) / float(total)
    z2 = float(z) ** 2
    denom = 1.0 + z2 / total
    center = p + z2 / (2.0 * total)
    margin = float(z) * math.sqrt((p * (1.0 - p) + z2 / (4.0 * total)) / total)
    return float((center - margin) / denom)


def apply_cross_market_disposition(
    crypto_internal_verdict: str,
    *,
    stock_analogue_preregistered: bool,
    stock_analogue_tested: bool,
) -> str:
    """Keep crypto diagnostics separate from the user's stock+crypto gate."""
    if crypto_internal_verdict != CRYPTO_FAVORABLE_VERDICT:
        return crypto_internal_verdict
    if stock_analogue_preregistered and stock_analogue_tested:
        return crypto_internal_verdict
    return CROSS_MARKET_UNTESTED_VERDICT


def day_cluster_ci(
    values: np.ndarray,
    days: pd.Series,
    *,
    draws: int = BOOTSTRAP_DRAWS,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float]:
    frame = pd.DataFrame({"value": np.asarray(values, dtype=float), "day": days.astype(str).to_numpy()})
    frame = frame[np.isfinite(frame["value"].to_numpy(float))]
    if frame.empty:
        return math.nan, math.nan
    daily = frame.groupby("day", sort=True)["value"].agg(["sum", "count"])
    if len(daily) < 2:
        return math.nan, math.nan
    sums = daily["sum"].to_numpy(float)
    counts = daily["count"].to_numpy(float)
    d = len(daily)
    rng = np.random.Generator(np.random.PCG64(seed))
    means = np.empty(draws, dtype=float)
    for b in range(draws):
        idx = rng.integers(0, d, size=d, dtype=np.int64, endpoint=False)
        means[b] = sums[idx].sum() / counts[idx].sum()
    low_rank = max(1, int(math.floor(0.025 * draws)))
    high_rank = min(draws, int(math.ceil(0.975 * draws)))
    return exact_order_stat(means, low_rank), exact_order_stat(means, high_rank)


def random_day_side_placebo(
    gross_bp: np.ndarray,
    days: pd.Series,
    *,
    cost_bp: float = PRIMARY_COST_BP,
    draws: int = RANDOM_DRAWS,
    seed: int = RANDOM_SEED,
) -> np.ndarray:
    frame = pd.DataFrame({"gross": np.asarray(gross_bp, dtype=float), "day": days.astype(str).to_numpy()})
    frame = frame[np.isfinite(frame["gross"].to_numpy(float))]
    if frame.empty:
        return np.array([], dtype=float)
    codes, unique_days = pd.factorize(frame["day"], sort=True)
    gross = frame["gross"].to_numpy(float)
    bitgen = np.random.PCG64(seed)
    result = np.empty(draws, dtype=float)
    for b in range(draws):
        words = bitgen.random_raw(len(unique_days))
        signs = np.where((words & np.uint64(1)) == np.uint64(1), 1.0, -1.0)
        result[b] = float((signs[codes] * gross).mean() - cost_bp)
    return result


def summarize_part(frame: pd.DataFrame, *, scope: str) -> dict[str, Any]:
    acted = frame[frame["action_side"].ne(0)].copy()
    base = {
        "scope": scope,
        "evaluation_n": int(len(frame)),
        "feature_known_n": int(frame["feature_known"].sum()),
        "acted_n": int(len(acted)),
        "hold_n": int(len(frame) - len(acted)),
        "action_rate": float(len(acted) / len(frame)) if len(frame) else math.nan,
    }
    if acted.empty:
        return base

    gross = acted["gross_return_bp"].to_numpy(float)
    side = acted["action_side"].to_numpy(float)
    selected_gross = side * gross
    net20 = selected_gross - PRIMARY_COST_BP
    net30 = selected_gross - STRESS_COST_BP
    direction_hits = selected_gross > 0
    direction_hit_n = int(direction_hits.sum())
    direction_hit_rate = float(direction_hits.mean())
    direction_wilson_lcb_95 = wilson_lower_bound(direction_hit_n, len(direction_hits))
    days = pd.to_datetime(acted["decision_ts_utc"], utc=True).dt.floor("D")
    daily_gross = pd.DataFrame({"day": days.astype(str), "gross": selected_gross}).groupby("day", sort=True)["gross"].mean()
    ci_low, ci_high = day_cluster_ci(net20, days)
    placebo = random_day_side_placebo(gross, days)
    p95_rank = min(len(placebo), int(math.floor(0.95 * len(placebo))) + 1) if len(placebo) else 0
    p95 = exact_order_stat(placebo, p95_rank) if p95_rank else math.nan

    k = int(math.ceil(0.01 * len(acted)))
    ranking = acted[["event_id", "decision_ts_utc"]].copy()
    ranking["_utc_day"] = pd.to_datetime(ranking["decision_ts_utc"], utc=True).dt.floor("D")
    ranking["_abs_selected_gross"] = np.abs(selected_gross)
    ranking["_row_position"] = np.arange(len(acted), dtype=int)
    ranking = ranking.sort_values(
        ["_abs_selected_gross", "_utc_day", "decision_ts_utc", "event_id"],
        ascending=[False, True, True, True],
        kind="stable",
    )
    remove_idx = ranking["_row_position"].iloc[:k].to_numpy(int)
    keep = np.ones(len(acted), dtype=bool)
    keep[remove_idx] = False
    raw_stats = outcome_magnitudes(acted["gross_return_bp"])

    base.update(
        {
            "long_n": int((side > 0).sum()),
            "short_n": int((side < 0).sum()),
            "active_utc_days": int(days.nunique()),
            "selected_direction_hit_n": direction_hit_n,
            "selected_direction_hit_rate": direction_hit_rate,
            "selected_direction_wilson_lcb_95": direction_wilson_lcb_95,
            **{f"raw_{k0}": v for k0, v in raw_stats.items()},
            "selected_gross_mean_bp": float(selected_gross.mean()),
            "net_20bp_mean_bp": float(net20.mean()),
            "net_30bp_mean_bp": float(net30.mean()),
            "breakeven_cost_bp": float(selected_gross.mean()),
            "trade_mde_95_bp": mde(selected_gross),
            "day_mde_95_bp": mde(daily_gross.to_numpy(float)),
            "day_cluster_ci_95_low_bp": ci_low,
            "day_cluster_ci_95_high_bp": ci_high,
            "top1pct_removed_n": k,
            "top1pct_abs_gross_removed_net20_mean_bp": float(net20[keep].mean()) if keep.any() else math.nan,
            "random_draws": RANDOM_DRAWS,
            "random_seed": RANDOM_SEED,
            "random_p95_order_stat_rank_1based": int(p95_rank),
            "random_net20_p95_bp": p95,
            "actual_exceeds_random_p95": bool(len(placebo) and float(net20.mean()) > p95),
        }
    )
    return base


def split_calibration_evaluation(joined: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    outcome_ok = (
        joined["path_complete"].fillna(False).astype(bool)
        & joined["eligible_for_horizon"].fillna(False).astype(bool)
        & pd.to_numeric(joined["gross_return_bp"], errors="coerce").notna()
    )
    calibration_mask = (
        joined["feature_known"].astype(bool)
        & outcome_ok
        & joined["decision_ts_utc"].lt(CUTOFF)
        & joined["exit_ts_utc"].le(CUTOFF)
    )
    evaluation_mask = (
        outcome_ok
        & joined["decision_ts_utc"].ge(CUTOFF)
    )
    return joined.loc[calibration_mask].copy(), joined.loc[evaluation_mask].copy()


def classify_verdict(
    overall: dict[str, Any],
    asset_stats: dict[str, dict[str, Any]],
    period_stats: dict[str, dict[str, Any]],
    comparator: dict[str, Any],
) -> tuple[str, dict[str, bool | None]]:
    n = int(overall.get("acted_n", 0) or 0)
    days = int(overall.get("active_utc_days", 0) or 0)
    net20 = float(overall.get("net_20bp_mean_bp", math.nan))
    direction_lcb = float(overall.get("selected_direction_wilson_lcb_95", math.nan))
    adequate = n >= MIN_EVAL_N and days >= MIN_ACTIVE_DAYS

    gates: dict[str, bool | None] = {
        "adequate_support": adequate,
        "selected_direction_wilson_lcb_95_gt_0_5": (
            bool(math.isfinite(direction_lcb) and direction_lcb > 0.5)
            if adequate
            else None
        ),
        "cluster_ci_lower_gt_0": bool(float(overall.get("day_cluster_ci_95_low_bp", math.nan)) > 0) if adequate else None,
        "net30_ge_0": bool(float(overall.get("net_30bp_mean_bp", math.nan)) >= 0) if adequate else None,
        "top1_removed_net20_gt_0": bool(float(overall.get("top1pct_abs_gross_removed_net20_mean_bp", math.nan)) > 0) if adequate else None,
        "actual_gt_random_p95": bool(overall.get("actual_exceeds_random_p95")) if adequate else None,
        "m1_incremental_pass": bool(comparator.get("m1_incremental_pass")) if adequate else None,
    }
    for asset in ("BTC", "ETH"):
        stats = asset_stats[asset]
        acted_n = int(stats.get("acted_n", 0) or 0)
        value = float(stats.get("net_20bp_mean_bp", math.nan))
        gates[f"{asset.lower()}_net20_ge_0_if_powered"] = None if acted_n < MIN_SUBGROUP_N else bool(math.isfinite(value) and value >= 0)
    for period in ("2025H2", "2026Q1"):
        stats = period_stats[period]
        acted_n = int(stats.get("acted_n", 0) or 0)
        value = float(stats.get("net_20bp_mean_bp", math.nan))
        gates[f"{period.lower()}_net20_gt_0_if_powered"] = None if acted_n < MIN_SUBGROUP_N else bool(math.isfinite(value) and value > 0)

    if not adequate:
        return "INDETERMINATE_UNDERPOWERED", gates
    if not math.isfinite(net20) or net20 <= 0:
        return "REJECT_CURRENT_ECONOMIC_FORM", gates
    applicable = [v for k, v in gates.items() if k != "adequate_support" and v is not None]
    if all(v is True for v in applicable):
        return CRYPTO_FAVORABLE_VERDICT, gates
    return "INDETERMINATE_POSITIVE_NOT_ROBUST", gates


def validate_inputs(
    ledger_root: Path,
    raw_paths: dict[str, Path],
) -> dict[str, Any]:
    manifest = json.loads((ledger_root / "manifest.json").read_text(encoding="utf-8"))
    qa = json.loads((ledger_root / "qa_summary.json").read_text(encoding="utf-8"))
    provenance = json.loads((ledger_root / "local_export_provenance.json").read_text(encoding="utf-8"))

    if qa.get("pass") is not True:
        raise ValueError("P0-A QA not pass")
    if provenance.get("publication_ready") is not True:
        raise ValueError("P0-A publication_ready is not true")
    if provenance.get("verification_status") != "PASS_AFTER_FIXTURE_REPAIR":
        raise ValueError("P0-A verification_status mismatch")
    if int(manifest.get("scope_event_count", -1)) != EXPECTED_ROWS:
        raise ValueError("P0-A scope row count mismatch")
    if manifest.get("scope_event_counts_by_asset") != EXPECTED_ASSET_COUNTS:
        raise ValueError("P0-A BTC/ETH counts mismatch")

    hashes: dict[str, Any] = {"p0a": {}, "raw": {}}
    for filename, expected in EXPECTED_P0A_SHA.items():
        digest = sha256_file(ledger_root / filename)
        if digest != expected:
            raise ValueError(f"P0-A SHA mismatch for {filename}")
        if manifest.get("output_sha256", {}).get("core" if filename.startswith("direction_event_core") else "outcomes") != expected:
            raise ValueError(f"P0-A manifest SHA mismatch for {filename}")
        hashes["p0a"][filename] = digest

    for asset, expected in EXPECTED_RAW_SHA.items():
        digest = sha256_file(raw_paths[asset])
        if digest != expected:
            raise ValueError(f"raw {asset} SHA mismatch")
        if manifest.get("known_frozen_source_sha256", {}).get(asset) != expected:
            raise ValueError(f"manifest known raw {asset} SHA mismatch")
        if manifest.get("actual_source_sha256", {}).get(asset) != expected:
            raise ValueError(f"manifest actual raw {asset} SHA mismatch")
        hashes["raw"][asset] = digest
    return hashes


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def run_validation(
    core: pd.DataFrame,
    outcomes: pd.DataFrame,
    feature_table: pd.DataFrame,
) -> dict[str, Any]:
    if len(core) != EXPECTED_ROWS or core["asset"].value_counts().to_dict() != EXPECTED_ASSET_COUNTS:
        raise ValueError("unexpected frozen P0-A event population")
    if core["event_id"].isna().any() or core["event_id"].duplicated().any():
        raise ValueError("core event_id must be unique/non-null")
    if feature_table["event_id"].isna().any() or feature_table["event_id"].duplicated().any():
        raise ValueError("feature event_id must be unique/non-null")

    out240 = outcomes[outcomes["horizon_min"].eq(HORIZON_MIN)].copy()
    if out240["event_id"].duplicated().any():
        raise ValueError("duplicate 240m outcome event_id")
    if len(out240) != EXPECTED_ROWS:
        raise ValueError("unexpected 240m outcome row count")

    joined = core[["event_id", "asset", "decision_ts_utc"]].copy()
    joined["asset"] = joined["asset"].astype(str).str.upper()
    joined["decision_ts_utc"] = pd.to_datetime(joined["decision_ts_utc"], utc=True)
    feat_cols = [
        "event_id", "feature_known", "missing_reason", "source_hour_start_utc",
        "source_hour_end_utc", "valid_minutes", "wick_skew"
    ]
    joined = joined.merge(feature_table[feat_cols], on="event_id", how="left", validate="one_to_one")
    outcome_cols = ["event_id", "path_complete", "eligible_for_horizon", "gross_return_bp", "exit_ts_utc"]
    joined = joined.merge(out240[outcome_cols], on="event_id", how="left", validate="one_to_one")
    joined["exit_ts_utc"] = pd.to_datetime(joined["exit_ts_utc"], utc=True)
    joined["source_hour_start_utc"] = pd.to_datetime(joined["source_hour_start_utc"], utc=True)
    joined["source_hour_end_utc"] = pd.to_datetime(joined["source_hour_end_utc"], utc=True)

    current_hour_start = joined["decision_ts_utc"].dt.floor("h")
    leakage = {
        "event_rows": int(len(joined)),
        "duplicate_event_ids": int(joined["event_id"].duplicated().sum()),
        "feature_hour_not_strictly_prior_violations": int(
            (
                joined["feature_known"].fillna(False).astype(bool)
                & joined["source_hour_end_utc"].ge(current_hour_start)
            ).sum()
        ),
    }
    if leakage["feature_hour_not_strictly_prior_violations"]:
        raise ValueError("current event hour leaked into feature")

    calibration, evaluation = split_calibration_evaluation(joined)
    model = fit_calibration_model(calibration)
    evaluation = apply_frozen_model(evaluation, model)
    comparator = probability_comparator(evaluation)

    overall = summarize_part(evaluation, scope="ALL")
    asset_stats = {
        asset: summarize_part(evaluation[evaluation["asset"].eq(asset)], scope=asset)
        for asset in ("BTC", "ETH")
    }
    periods = {
        "2025H2": (pd.Timestamp("2025-07-01T00:00:00Z"), pd.Timestamp("2026-01-01T00:00:00Z")),
        "2026Q1": (pd.Timestamp("2026-01-01T00:00:00Z"), pd.Timestamp("2026-04-01T00:00:00Z")),
    }
    period_stats = {
        name: summarize_part(
            evaluation[evaluation["decision_ts_utc"].ge(start) & evaluation["decision_ts_utc"].lt(end)],
            scope=name,
        )
        for name, (start, end) in periods.items()
    }
    crypto_internal_verdict, gates = classify_verdict(
        overall, asset_stats, period_stats, comparator
    )
    stock_analogue_preregistered = False
    stock_analogue_tested = False
    verdict = apply_cross_market_disposition(
        crypto_internal_verdict,
        stock_analogue_preregistered=stock_analogue_preregistered,
        stock_analogue_tested=stock_analogue_tested,
    )

    acted = evaluation[evaluation["action_side"].ne(0)].copy()
    hour_diagnostics = {
        str(int(hour)): summarize_part(part, scope=f"UTC_HOUR_{int(hour):02d}")
        for hour, part in acted.groupby(acted["decision_ts_utc"].dt.hour, sort=True)
    } if len(acted) else {}
    weekday_diagnostics = {
        str(int(day)): summarize_part(part, scope=f"UTC_WEEKDAY_{int(day)}")
        for day, part in acted.groupby(acted["decision_ts_utc"].dt.weekday, sort=True)
    } if len(acted) else {}

    missing_reasons = Counter(
        str(x) for x in feature_table.loc[~feature_table["feature_known"].astype(bool), "missing_reason"].fillna("UNKNOWN")
    )
    return json_ready(
        {
            "schema_version": 1,
            "idea": "W7017-DIR-016",
            "validator_prep_worker": "WORKER1924",
            "numeric_result_owner": "WORKER5300",
            "evidence_status": "REUSED_HISTORICAL_HOLDOUT",
            "promotion_allowed": False,
            "protocol": {
                "prior_hour_alignment": "PREVIOUS_FULL_UTC_HOUR",
                "constituent_minutes": 60,
                "wick_epsilon": "max(1e-12,abs(close)*1e-12)",
                "quantile_method": "numpy.quantile(method=linear)",
                "bucket_assignment": "searchsorted(bounds,x,side=left)+1",
                "horizon_min": HORIZON_MIN,
                "cutoff_utc": CUTOFF,
                "primary_cost_bp": PRIMARY_COST_BP,
                "stress_cost_bp": STRESS_COST_BP,
                "ev_separation_bp": EV_SEPARATION_BP,
                "min_cell_n": MIN_CELL_N,
                "min_up_n": MIN_UP_N,
                "min_nonup_n": MIN_NONUP_N,
                "bootstrap_draws": BOOTSTRAP_DRAWS,
                "bootstrap_seed": BOOTSTRAP_SEED,
                "bootstrap_rng_primitive": "Generator(PCG64(seed)).integers(0,D,size=D,dtype=int64,endpoint=False) once per draw",
                "bootstrap_ci_order_stats_1based": [125, 4875],
                "random_draws": RANDOM_DRAWS,
                "random_seed": RANDOM_SEED,
                "random_rng_primitive": "PCG64(seed).random_raw(D) once per draw; odd=LONG even=SHORT",
                "random_p95_order_stat_1based": 9501,
                "top1pct_tie_break": "abs selected gross desc, UTC date asc, decision_ts_utc asc, UTF-8 event_id asc",
                "trade_mde_definition": "1.96*sample_sd(selected_gross_bp,ddof=1)/sqrt(N_acted)",
                "day_mde_definition": "1.96*sample_sd(equal-weight acted-date mean selected_gross_bp,ddof=1)/sqrt(D_acted)",
            },
            "feature_coverage": {
                "rows": int(len(feature_table)),
                "known_n": int(feature_table["feature_known"].sum()),
                "missing_n": int((~feature_table["feature_known"].astype(bool)).sum()),
                "missing_reasons": dict(sorted(missing_reasons.items())),
            },
            "calibration_n": int(len(calibration)),
            "evaluation_n": int(len(evaluation)),
            "calibration_model": model,
            "information_comparator": comparator,
            "evaluation_overall": overall,
            "asset_scopes": asset_stats,
            "period_scopes": period_stats,
            "hour_diagnostics": hour_diagnostics,
            "weekday_diagnostics": weekday_diagnostics,
            "retrospective_gates": gates,
            "crypto_internal_verdict": crypto_internal_verdict,
            "cross_market_robustness": {
                "stock_analogue_preregistered": stock_analogue_preregistered,
                "stock_analogue_tested": stock_analogue_tested,
                "overall_gate": (
                    "PASS"
                    if stock_analogue_preregistered and stock_analogue_tested
                    else "NOT_TESTED"
                ),
                "policy": (
                    "A crypto-only favorable internal result is overall "
                    "INDETERMINATE until a preregistered stock analogue is tested; "
                    "do not invent or fit a stock analogue after outcome access."
                ),
            },
            "leakage_audit": {
                **leakage,
                "calibration_exit_after_cutoff_violations": int((calibration["exit_ts_utc"] > CUTOFF).sum()),
                "evaluation_refit": False,
                "event_reselection": False,
            },
            "verdict": verdict,
            "interpretation_ceiling": CROSS_MARKET_UNTESTED_VERDICT,
        }
    )


def main() -> None:
    args = parse_args()
    ledger_root = resolve(args.ledger_root)
    raw_paths = {"BTC": resolve(args.btc_bars), "ETH": resolve(args.eth_bars)}
    out_path = resolve(args.out)

    before = validate_inputs(ledger_root, raw_paths)
    core = pd.read_parquet(ledger_root / "direction_event_core.parquet")
    outcomes = pd.read_parquet(ledger_root / "direction_outcome.parquet")
    bars_by_asset = {asset: read_bars(path) for asset, path in raw_paths.items()}
    feature_table = build_feature_table(core, bars_by_asset)
    result = run_validation(core, outcomes, feature_table)
    after = validate_inputs(ledger_root, raw_paths)
    if before != after:
        raise RuntimeError("input hashes changed during validation")

    result["input_sha256"] = before
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(json_ready(result), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"idea": result["idea"], "verdict": result["verdict"], "out": str(out_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
