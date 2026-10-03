#!/usr/bin/env python3
"""Mechanical local-source export for W7017-DIR-016.

Exports only exact raw OHLC rows from the previous fully completed UTC hour for
each frozen P0-A BTC/ETH event. No wick feature, return, label, action, outcome,
economics, inference, or verdict is computed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORE = ROOT / "data/direction_event_ledger/p0a_ohlcv/direction_event_core.parquet"
DEFAULT_BTC = ROOT / "data/okx_swap_multi/BTC-USDT-SWAP_1m.parquet"
DEFAULT_ETH = ROOT / "data/okx_swap_multi/ETH-USDT-SWAP_1m.parquet"
DEFAULT_OUT = ROOT / "data/direction_idea_bank/w7017_dir016"

EXPECTED_CORE_SHA256 = "13bbd824115d023cdc8c98a3aa596c70d1e037af779d3c314dc76f6ea3bc41ad"
EXPECTED_RAW_SHA256 = {
    "BTC": "34fc490ff3df8bdf0d70d102d2acbe6576876353ce7c125ab623ce195ee31abc",
    "ETH": "6d090908df785ba77e85256bc324354fe6716823908306bedfa1ad1851c46809",
}
EXPECTED_EVENT_COUNTS = {"BTC": 535, "ETH": 612}
EXPECTED_TOTAL_EVENTS = 1147
EXPECTED_MINUTES = 60
OHLC = ["open", "high", "low", "close"]

SLICE_COLUMNS = [
    "event_id", "asset", "decision_ts_utc", "current_hour_start_utc",
    "source_hour_start_utc", "source_hour_end_utc", "source_minute_utc",
    "minute_offset", "open", "high", "low", "close", "source_sha256",
]
AVAILABILITY_COLUMNS = [
    "event_id", "asset", "decision_ts_utc", "current_hour_start_utc",
    "source_hour_start_utc", "source_hour_end_utc", "expected_rows",
    "observed_rows", "valid_ohlc_rows", "complete_window", "missing_reason",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--core", type=Path, default=DEFAULT_CORE)
    p.add_argument("--btc-1m", type=Path, default=DEFAULT_BTC)
    p.add_argument("--eth-1m", type=Path, default=DEFAULT_ETH)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    return p.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify_sha(path: Path, expected: str, label: str) -> str:
    if not path.exists():
        raise FileNotFoundError(path)
    got = sha256_file(path)
    if got != expected:
        raise ValueError(f"{label} SHA256 mismatch: {got} != {expected}")
    return got


def load_events(core_path: Path) -> pd.DataFrame:
    core = pd.read_parquet(core_path)
    need = {"event_id", "asset", "decision_ts_utc"}
    missing = need - set(core.columns)
    if missing:
        raise ValueError(f"core missing columns: {sorted(missing)}")
    if core["event_id"].isna().any() or core["event_id"].duplicated().any():
        raise ValueError("core event_id must be unique/non-null")

    out = core[["event_id", "asset", "decision_ts_utc"]].copy()
    out["asset"] = out["asset"].astype(str).str.upper()
    if len(out) != EXPECTED_TOTAL_EVENTS:
        raise ValueError(f"expected {EXPECTED_TOTAL_EVENTS} events, found {len(out)}")
    counts = out["asset"].value_counts().to_dict()
    if counts != EXPECTED_EVENT_COUNTS:
        raise ValueError(f"asset counts mismatch: {counts}")

    out["decision_ts_utc"] = pd.to_datetime(out["decision_ts_utc"], utc=True, errors="coerce")
    if out["decision_ts_utc"].isna().any():
        raise ValueError("invalid decision timestamp")
    return out.sort_values(["decision_ts_utc", "event_id"], kind="stable").reset_index(drop=True)


def load_ohlc(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path, columns=OHLC)
    index = pd.to_datetime(frame.index, utc=True, errors="coerce")
    if index.isna().any():
        raise ValueError("minute source has invalid timestamp")
    if index.duplicated().any():
        raise ValueError("minute source has duplicate timestamp")
    out = frame.copy()
    out.index = pd.DatetimeIndex(index)
    for c in OHLC:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out.sort_index()


def ohlc_valid(frame: pd.DataFrame) -> pd.Series:
    finite = np.isfinite(frame[OHLC].to_numpy(float)).all(axis=1)
    positive = frame[OHLC].gt(0).all(axis=1).to_numpy()
    high_ok = frame["high"].ge(frame[["open", "close", "low"]].max(axis=1)).to_numpy()
    low_ok = frame["low"].le(frame[["open", "close", "high"]].min(axis=1)).to_numpy()
    return pd.Series(finite & positive & high_ok & low_ok, index=frame.index)


def export_source_slice(
    events: pd.DataFrame,
    bars_by_asset: dict[str, pd.DataFrame],
    *,
    source_sha256: dict[str, str] = EXPECTED_RAW_SHA256,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    source_rows: list[dict[str, object]] = []
    availability_rows: list[dict[str, object]] = []

    for row in events.itertuples(index=False):
        event_id = str(row.event_id)
        asset = str(row.asset).upper()
        decision = pd.Timestamp(row.decision_ts_utc)
        current_hour_start = decision.floor("h")
        source_hour_start = current_hour_start - pd.Timedelta(hours=1)
        source_hour_end = current_hour_start - pd.Timedelta(minutes=1)
        expected = pd.date_range(source_hour_start, source_hour_end, freq="1min", tz="UTC")
        if len(expected) != EXPECTED_MINUTES:
            raise RuntimeError("expected previous UTC hour to contain exactly 60 minute labels")

        observed = bars_by_asset[asset].reindex(expected)
        observed_mask = observed[OHLC].notna().any(axis=1)
        valid_mask = ohlc_valid(observed)
        observed_rows = int(observed_mask.sum())
        valid_rows = int(valid_mask.sum())
        complete = bool(observed_rows == EXPECTED_MINUTES and valid_rows == EXPECTED_MINUTES)
        if complete:
            reason = ""
        elif observed_rows < EXPECTED_MINUTES:
            reason = "MISSING_MINUTE"
        else:
            reason = "INVALID_OHLC"

        for offset, ts in enumerate(expected, start=-EXPECTED_MINUTES):
            vals = observed.loc[ts, OHLC]
            if vals.isna().all():
                continue
            source_rows.append({
                "event_id": event_id,
                "asset": asset,
                "decision_ts_utc": decision,
                "current_hour_start_utc": current_hour_start,
                "source_hour_start_utc": source_hour_start,
                "source_hour_end_utc": source_hour_end,
                "source_minute_utc": ts,
                "minute_offset": int(offset),
                "open": None if pd.isna(vals["open"]) else float(vals["open"]),
                "high": None if pd.isna(vals["high"]) else float(vals["high"]),
                "low": None if pd.isna(vals["low"]) else float(vals["low"]),
                "close": None if pd.isna(vals["close"]) else float(vals["close"]),
                "source_sha256": source_sha256[asset],
            })

        availability_rows.append({
            "event_id": event_id,
            "asset": asset,
            "decision_ts_utc": decision,
            "current_hour_start_utc": current_hour_start,
            "source_hour_start_utc": source_hour_start,
            "source_hour_end_utc": source_hour_end,
            "expected_rows": EXPECTED_MINUTES,
            "observed_rows": observed_rows,
            "valid_ohlc_rows": valid_rows,
            "complete_window": complete,
            "missing_reason": reason,
        })

    source_slice = pd.DataFrame(source_rows, columns=SLICE_COLUMNS)
    availability = pd.DataFrame(availability_rows, columns=AVAILABILITY_COLUMNS)
    if len(availability) != len(events) or availability["event_id"].duplicated().any():
        raise RuntimeError("availability identity drift")
    if not source_slice.empty:
        src = pd.to_datetime(source_slice["source_minute_utc"], utc=True)
        hour = pd.to_datetime(source_slice["current_hour_start_utc"], utc=True)
        dec = pd.to_datetime(source_slice["decision_ts_utc"], utc=True)
        if (src >= hour).any() or (hour > dec).any():
            raise RuntimeError("source slice crosses decision/current-hour boundary")
        forbidden_tokens = (
            "return", "wick", "skew", "label", "action", "outcome", "future",
            "pnl", "profit", "bootstrap", "inference", "verdict",
        )
        forbidden = [c for c in source_slice.columns if any(t in c.lower() for t in forbidden_tokens)]
        if forbidden:
            raise RuntimeError(f"research-semantic columns forbidden: {forbidden}")
    return source_slice, availability


def _json_scalar(value: object) -> object:
    """Convert one mechanical source value to strict JSON without research transforms."""
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    return value


def build_event_window_records(
    source_slice: pd.DataFrame,
    availability: pd.DataFrame,
    *,
    source_sha256: dict[str, str] = EXPECTED_RAW_SHA256,
) -> list[dict[str, object]]:
    """Losslessly group the existing raw source rows by frozen event identity."""
    groups = {
        str(event_id): group.sort_values(["minute_offset", "source_minute_utc"], kind="stable")
        for event_id, group in source_slice.groupby("event_id", sort=False)
    }
    records: list[dict[str, object]] = []

    for row in availability.itertuples(index=False):
        event_id = str(row.event_id)
        asset = str(row.asset).upper()
        group = groups.get(event_id)
        if group is None:
            group = source_slice.iloc[0:0].copy()

        if len(group) != int(row.observed_rows):
            raise RuntimeError(
                f"event-window/source-row count mismatch for {event_id}: "
                f"{len(group)} != {int(row.observed_rows)}"
            )
        if not group.empty:
            if set(group["asset"].astype(str).str.upper().unique()) != {asset}:
                raise RuntimeError(f"event-window asset mismatch for {event_id}")
            if set(group["source_sha256"].astype(str).unique()) != {source_sha256[asset]}:
                raise RuntimeError(f"event-window source SHA mismatch for {event_id}")

        raw_rows: list[dict[str, object]] = []
        for src in group.itertuples(index=False):
            raw_rows.append({
                "source_minute_utc": _json_scalar(pd.Timestamp(src.source_minute_utc)),
                "minute_offset": int(src.minute_offset),
                "open": _json_scalar(src.open),
                "high": _json_scalar(src.high),
                "low": _json_scalar(src.low),
                "close": _json_scalar(src.close),
            })

        records.append({
            "event_id": event_id,
            "asset": asset,
            "decision_ts_utc": _json_scalar(pd.Timestamp(row.decision_ts_utc)),
            "current_hour_start_utc": _json_scalar(pd.Timestamp(row.current_hour_start_utc)),
            "source_hour_start_utc": _json_scalar(pd.Timestamp(row.source_hour_start_utc)),
            "source_hour_end_utc": _json_scalar(pd.Timestamp(row.source_hour_end_utc)),
            "source_sha256": source_sha256[asset],
            "expected_rows": int(row.expected_rows),
            "observed_rows": int(row.observed_rows),
            "valid_ohlc_rows": int(row.valid_ohlc_rows),
            "complete_window": bool(row.complete_window),
            "missing_reason": "" if pd.isna(row.missing_reason) else str(row.missing_reason),
            "rows": raw_rows,
        })

    if len(records) != len(availability):
        raise RuntimeError("event-window identity drift")
    if len({str(x["event_id"]) for x in records}) != len(records):
        raise RuntimeError("duplicate event_id in event-window mirror")
    if sum(len(x["rows"]) for x in records) != len(source_slice):
        raise RuntimeError("event-window mirror is not lossless versus source slice")
    return records


def write_outputs(
    out_dir: Path,
    source_slice: pd.DataFrame,
    availability: pd.DataFrame,
    *,
    core_path: Path,
    raw_paths: dict[str, Path],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    slice_path = out_dir / "prior_hour_ohlc_source_slice.parquet"
    availability_path = out_dir / "prior_hour_source_availability.csv"
    event_windows_path = out_dir / "event_windows.jsonl"
    manifest_path = out_dir / "prior_hour_source_manifest.json"

    source_slice.to_parquet(slice_path, index=False)
    availability.to_csv(availability_path, index=False)
    event_windows = build_event_window_records(source_slice, availability)
    event_windows_path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
            for record in event_windows
        ),
        encoding="utf-8",
    )

    manifest = {
        "schema_version": 1,
        "status": "W7017_DIR016_PRIOR_HOUR_SOURCE_SLICE_EXPORT_COMPLETE",
        "task_class": "LOCAL_SOURCE_EXPORT",
        "transform_class": "SUBSET_EXPORT",
        "semantic_owner": "GPT",
        "event_count": int(len(availability)),
        "event_counts_by_asset": {
            str(k): int(v) for k, v in availability["asset"].value_counts().sort_index().items()
        },
        "expected_rows_per_event": EXPECTED_MINUTES,
        "source_rows": int(len(source_slice)),
        "complete_events": int(availability["complete_window"].astype(bool).sum()),
        "incomplete_events": int((~availability["complete_window"].astype(bool)).sum()),
        "core_sha256": sha256_file(core_path),
        "raw_source_sha256": {a: sha256_file(p) for a, p in raw_paths.items()},
        "source_slice_sha256": sha256_file(slice_path),
        "source_availability_sha256": sha256_file(availability_path),
        "event_windows_sha256": sha256_file(event_windows_path),
        "event_windows_rows": int(len(event_windows)),
        "event_windows_source_rows": int(sum(len(record["rows"]) for record in event_windows)),
        "event_windows_semantics": "lossless_event_grouping_of_prior_hour_raw_ohlc_source_slice",
        "aggregation_performed": False,
        "research_features_computed": False,
        "returns_computed": False,
        "wick_computed": False,
        "outcome_table_opened": False,
        "statistical_inference_computed": False,
        "event_reselection_performed": False,
        "network_download_performed": False,
        "output_columns": list(source_slice.columns),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    a = parse_args()
    core_path = resolve(a.core)
    raw_paths = {"BTC": resolve(a.btc_1m), "ETH": resolve(a.eth_1m)}
    out_dir = resolve(a.out_dir)

    verify_sha(core_path, EXPECTED_CORE_SHA256, "P0-A core")
    for asset, path in raw_paths.items():
        verify_sha(path, EXPECTED_RAW_SHA256[asset], f"{asset} 1m")

    events = load_events(core_path)
    bars = {asset: load_ohlc(path) for asset, path in raw_paths.items()}
    source_slice, availability = export_source_slice(events, bars)
    write_outputs(out_dir, source_slice, availability, core_path=core_path, raw_paths=raw_paths)
    print(json.dumps({
        "events": int(len(availability)),
        "source_rows": int(len(source_slice)),
        "complete_events": int(availability["complete_window"].astype(bool).sum()),
        "event_windows": int(len(availability)),
        "out_dir": str(out_dir),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
