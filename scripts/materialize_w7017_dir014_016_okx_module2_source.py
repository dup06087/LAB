#!/usr/bin/env python3
"""Outcome-blind OKX module=2 source materializer for W7017-DIR-014/016.

This is a provider-side replacement for the exact-local byte-export boundary,
not a research-feature builder.  It inventories official OKX module=2 monthly
1m candlestick archives, downloads only URLs returned by that official
inventory response, verifies a positive bit-exact overlap against committed
P0-A OHLCV primitives, and projects the admitted OHLC bytes into the already
registered DIR014 or DIR016 source-output schema.

No return/semivariance/wick/action/outcome/economic/inference/verdict is
computed.  Any source/provenance/parity ambiguity fails closed.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import math
import os
import re
import struct
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
P0A = ROOT / "data/direction_event_ledger/p0a_ohlcv"
DEFAULT_CORE = P0A / "direction_event_core.parquet"
DEFAULT_FEATURES = P0A / "direction_feature_ohlcv.parquet"
EXPECTED_CORE_SHA256 = "13bbd824115d023cdc8c98a3aa596c70d1e037af779d3c314dc76f6ea3bc41ad"
EXPECTED_FEATURE_SHA256 = "9d167fef1f03c259b21c8c09e94f585b420f9de0a3dc0cec709e670fea1cc238"
EXPECTED_EVENTS = 1147
EXPECTED_ASSET_COUNTS = {"BTC": 535, "ETH": 612}
LINEAGE_REFERENCE_SHA256 = {
    "p0a_core": EXPECTED_CORE_SHA256,
    "btc_1m": "34fc490ff3df8bdf0d70d102d2acbe6576876353ce7c125ab623ce195ee31abc",
    "eth_1m": "6d090908df785ba77e85256bc324354fe6716823908306bedfa1ad1851c46809",
}
INST = {"BTC": "BTC-USDT-SWAP", "ETH": "ETH-USDT-SWAP"}
FAMILY = {"BTC": "BTC-USDT", "ETH": "ETH-USDT"}
OHLC = ["open", "high", "low", "close"]

BASE_URL = "https://www.okx.com"
BULK_PATH = "/api/v5/public/market-data-history"
BULK_STATIC_HOST = "static.okx.com"
MAX_MONTHS_PER_QUERY = 10
USER_AGENT = "trading-worker4094-w7017-module2-materializer/1.0"
PROVIDER_MODE = "GPT_AUTHORITATIVE_OKX_UPSTREAM_REGENERATION"

RAW10_SCHEMA = frozenset({
    "instrument_name", "open", "high", "low", "close", "vol",
    "vol_ccy", "vol_ccy_quote", "open_time", "confirm",
})
NATIVE8_SCHEMA = frozenset({
    "open_time", "open", "high", "low", "close", "volume",
    "vol_ccy", "vol_ccy_quote",
})
PARITY_COLUMNS = (
    "ret_240m_bp",
    "rv_240m_bp",
    "ma_distance_240m_bp",
    "drawdown_from_high_240m_bp",
    "runup_from_low_240m_bp",
    "high_low_range_240m_bp",
    "last_bar_body_bp",
    "last_bar_range_bp",
    "last_bar_upper_wick_ratio",
    "last_bar_lower_wick_ratio",
    "last_bar_close_location",
)

TARGETS: dict[str, dict[str, Any]] = {
    "dir014": {
        "months": ("2024-09", "2026-04", 20),
        "task_id": "worker5300-w7017-dir014-24h-source-slice-codex-20260927",
        "exporter": "scripts/export_w7017_dir014_24h_source_slice.py",
        "exporter_blob": "cd159698b3850b81e4002b2846c626498fc7bfce",
        "out_dir": "data/direction_idea_bank/w7017_dir014",
        "receipt": "artifacts/control_plane/w7017_dir014_source_export_run_receipt_20260930.json",
        "receipt_runs": "artifacts/control_plane/w7017_dir014_source_export_run_receipt_runs",
        "manifest_status": "W7017_DIR014_24H_SOURCE_SLICE_EXPORT_COMPLETE",
        "manifest_name": "raw_24h_source_manifest.json",
        "source_name": "raw_24h_ohlc_union.parquet",
        "availability_name": "event_window_index.csv",
        "event_windows_name": "event_close_windows.jsonl",
        "boundary": {
            "boundary_event_rows": 1147,
            "boundary_btc_events": 535,
            "boundary_eth_events": 612,
            "boundary_expected_rows_per_event": 1441,
            "boundary_total_logical_event_minutes": 1652827,
            "boundary_btc_union_minutes": 383496,
            "boundary_eth_union_minutes": 436355,
            "boundary_total_asset_union_minutes": 819851,
            "boundary_sha256": "c484d8e1e223b4fdd8ad009871804833170df492b82aa763e9b96e85b8a5c560",
        },
    },
    "dir016": {
        "months": ("2024-10", "2026-04", 19),
        "task_id": "worker5300-w7017-dir016-prior-hour-source-slice-codex-20260927",
        "exporter": "scripts/export_w7017_dir016_prior_hour_source_slice.py",
        "exporter_blob": "c02f63814768ee49233d50574b8ccc6eca83c4e8",
        "out_dir": "data/direction_idea_bank/w7017_dir016",
        "receipt": "artifacts/control_plane/w7017_dir016_source_export_run_receipt_20260930.json",
        "receipt_runs": "artifacts/control_plane/w7017_dir016_source_export_run_receipt_runs",
        "manifest_status": "W7017_DIR016_PRIOR_HOUR_SOURCE_SLICE_EXPORT_COMPLETE",
        "manifest_name": "prior_hour_source_manifest.json",
        "source_name": "prior_hour_ohlc_source_slice.parquet",
        "availability_name": "prior_hour_source_availability.csv",
        "event_windows_name": "event_windows.jsonl",
        "clock": {
            "clock_events": 1147,
            "clock_btc_events": 535,
            "clock_eth_events": 612,
            "clock_ordered_rows": 68820,
            "clock_unique_physical_asset_minutes": 65820,
            "clock_ordered_sha256": "78662ce9e7c295956582f104babd03fc57b117217b7cc86caa87cf8689346be9",
            "clock_physical_source_key_sha256": "229555bd1aa526800da419a93bfe1782383dac41872d648bbd3ab03b67b47c26",
        },
    },
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--target", required=True, choices=sorted(TARGETS))
    p.add_argument("--core", type=Path, default=DEFAULT_CORE)
    p.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    p.add_argument("--out-dir", type=Path)
    return p.parse_args()


def resolve(path: Path | str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def canonical_json_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def git_blob_sha(path: Path) -> str:
    payload = path.read_bytes()
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def verify_sha(path: Path, expected: str, label: str) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)
    got = sha256_file(path)
    if got != expected:
        raise ValueError(f"{label} SHA256 mismatch: {got} != {expected}")
    return got


def month_labels(start: str, end: str, expected_count: int) -> list[str]:
    labels = pd.period_range(start, end, freq="M").astype(str).tolist()
    if len(labels) != expected_count or labels[0] != start or labels[-1] != end:
        raise ValueError("module=2 frozen month lattice drift")
    return labels


def month_start_utc8_as_utc(label: str) -> pd.Timestamp:
    anchor = pd.Timestamp(f"{label}-01T00:00:00Z")
    if anchor.strftime("%Y-%m") != label:
        raise ValueError(f"invalid month label {label!r}")
    return anchor - pd.Timedelta(hours=8)


def next_month_start_utc8_as_utc(label: str) -> pd.Timestamp:
    anchor = pd.Timestamp(f"{label}-01T00:00:00Z")
    return (anchor + pd.offsets.MonthBegin(1)) - pd.Timedelta(hours=8)


def query_chunks(labels: list[str]) -> list[list[str]]:
    if labels != sorted(set(labels)):
        raise ValueError("month labels must be sorted and unique")
    return [labels[i:i + MAX_MONTHS_PER_QUERY] for i in range(0, len(labels), MAX_MONTHS_PER_QUERY)]


def query_bounds_ms(chunk: list[str]) -> tuple[int, int]:
    if not chunk or len(chunk) > MAX_MONTHS_PER_QUERY:
        raise ValueError("invalid module=2 month chunk")
    begin = month_start_utc8_as_utc(chunk[0])
    end = next_month_start_utc8_as_utc(chunk[-1]) - pd.Timedelta(days=1)
    return int(begin.value // 1_000_000), int(end.value // 1_000_000)


def request_inventory_page(asset: str, begin_ms: int, end_ms: int) -> dict[str, Any]:
    params = {
        "module": "2",
        "instType": "SWAP",
        "instFamilyList": FAMILY[asset],
        "dateAggrType": "monthly",
        "begin": str(int(begin_ms)),
        "end": str(int(end_ms)),
    }
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            response = requests.get(
                BASE_URL + BULK_PATH,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != "0":
                raise RuntimeError(
                    f"OKX module=2 code={payload.get('code')} msg={payload.get('msg')}"
                )
            return payload
        except Exception as exc:
            last_error = exc
            if attempt < 5:
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"OKX module=2 inventory request failed: {last_error}")


def parse_inventory(
    payloads: list[dict[str, Any]],
    *,
    asset: str,
    required_labels: list[str],
) -> list[dict[str, str]]:
    required = set(required_labels)
    inst = INST[asset]
    family = FAMILY[asset]
    pattern = re.compile(rf"^{re.escape(inst)}-candlesticks-(\d{{4}}-\d{{2}})\.zip$")
    found: dict[str, dict[str, str]] = {}
    for payload in payloads:
        if payload.get("code") != "0":
            raise ValueError("module=2 inventory payload code drift")
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError("module=2 inventory data must be a list")
        for group in data:
            if not isinstance(group, dict) or group.get("dateAggrType") != "monthly":
                raise ValueError("module=2 inventory aggregation drift")
            details = group.get("details")
            if not isinstance(details, list):
                raise ValueError("module=2 inventory details must be a list")
            for detail in details:
                if not isinstance(detail, dict):
                    raise ValueError("module=2 detail must be an object")
                if detail.get("instType") != "SWAP":
                    continue
                if detail.get("instFamily") != family:
                    continue
                rows = detail.get("groupDetails")
                if not isinstance(rows, list):
                    raise ValueError("module=2 groupDetails must be a list")
                for item in rows:
                    if not isinstance(item, dict):
                        raise ValueError("module=2 group detail must be an object")
                    filename = str(item.get("filename", ""))
                    match = pattern.fullmatch(filename)
                    if match is None:
                        raise ValueError(f"unexpected module=2 filename {filename!r}")
                    label = match.group(1)
                    if label not in required:
                        continue
                    url = str(item.get("url", ""))
                    parsed = urlparse(url)
                    if parsed.scheme != "https" or parsed.hostname != BULK_STATIC_HOST:
                        raise ValueError(f"module=2 URL host drift: {url!r}")
                    if Path(parsed.path).name != filename:
                        raise ValueError("module=2 filename/URL mismatch")
                    row = {
                        "asset": asset,
                        "month": label,
                        "filename": filename,
                        "url": url,
                        "sizeMB": str(item.get("sizeMB", "")),
                    }
                    prior = found.get(label)
                    if prior is not None and prior != row:
                        raise ValueError(f"conflicting inventory for {asset} {label}")
                    found[label] = row
    missing = sorted(required - set(found))
    if missing:
        raise ValueError(f"module=2 inventory missing {asset} months: {missing}")
    return [found[label] for label in required_labels]


def fetch_inventory(asset: str, labels: list[str]) -> list[dict[str, str]]:
    payloads: list[dict[str, Any]] = []
    for chunk in query_chunks(labels):
        begin_ms, end_ms = query_bounds_ms(chunk)
        payloads.append(request_inventory_page(asset, begin_ms, end_ms))
    return parse_inventory(payloads, asset=asset, required_labels=labels)


def download_archive(url: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != BULK_STATIC_HOST:
        raise ValueError("archive URL must be an official inventory-returned static.okx.com URL")
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=90)
            response.raise_for_status()
            return response.content
        except Exception as exc:
            last_error = exc
            if attempt < 5:
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"OKX module=2 archive download failed: {last_error}")


def _valid_ohlc(o: float, h: float, lo: float, c: float) -> bool:
    return bool(
        all(math.isfinite(x) and x > 0.0 for x in (o, h, lo, c))
        and h >= max(o, c, lo)
        and lo <= min(o, c, h)
    )


def parse_archive(
    payload: bytes,
    *,
    asset: str,
    month: str,
) -> tuple[dict[int, tuple[float, float, float, float]], dict[str, Any]]:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if len(members) != 1:
                raise ValueError("module=2 archive must contain exactly one CSV")
            member = members[0]
            csv_bytes = archive.read(member)
    except zipfile.BadZipFile as exc:
        raise ValueError("module=2 payload is not a valid ZIP") from exc

    frame = pd.read_csv(io.BytesIO(csv_bytes))
    columns = frozenset(str(x) for x in frame.columns)
    if columns == RAW10_SCHEMA:
        schema_variant = "OKX_MODULE2_RAW_10COL_WITH_INSTRUMENT_CONFIRM"
        instruments = set(frame["instrument_name"].astype(str))
        if instruments != {INST[asset]}:
            raise ValueError(f"module=2 archive instrument drift: {sorted(instruments)}")
        frame["confirm"] = pd.to_numeric(frame["confirm"], errors="raise").astype(int)
        if not frame["confirm"].eq(1).all():
            raise ValueError("module=2 archive contains unconfirmed candle")
        completion_evidence = "ROW_CONFIRM_EQ_1"
    elif columns == NATIVE8_SCHEMA:
        schema_variant = "OKX_MODULE2_VENUE_NATIVE_8COL_ARCHIVE"
        frame["confirm"] = 1
        completion_evidence = "OFFICIAL_CLOSED_MONTHLY_MODULE2_ARCHIVE"
    else:
        raise ValueError(
            f"module=2 archive schema drift: {sorted(columns)!r}"
        )
    if frame.empty:
        raise ValueError("module=2 archive CSV is empty")
    for column in ("open_time", *OHLC):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    frame = frame.sort_values("open_time", kind="mergesort").reset_index(drop=True)

    duplicate = frame["open_time"].duplicated(keep=False)
    if duplicate.any():
        conflict: list[int] = []
        for timestamp, group in frame.loc[duplicate].groupby("open_time", sort=True):
            if len(group[[*OHLC, "confirm"]].drop_duplicates()) != 1:
                conflict.append(int(timestamp))
        if conflict:
            raise ValueError(f"conflicting duplicate timestamps: {conflict[:5]}")
        frame = frame.drop_duplicates(subset=["open_time"], keep="first").reset_index(drop=True)

    start_ms = int(month_start_utc8_as_utc(month).value // 1_000_000)
    end_ms = int(next_month_start_utc8_as_utc(month).value // 1_000_000)
    if int(frame["open_time"].min()) < start_ms or int(frame["open_time"].max()) >= end_ms:
        raise ValueError("archive timestamp outside named UTC+8 month")

    rows: dict[int, tuple[float, float, float, float]] = {}
    for row in frame.itertuples(index=False):
        ts_ms = int(row.open_time)
        o, h, lo, c = (float(getattr(row, col)) for col in OHLC)
        if not _valid_ohlc(o, h, lo, c):
            raise ValueError(f"invalid OHLC at {asset} {ts_ms}")
        rows[ts_ms] = (o, h, lo, c)
    audit = {
        "asset": asset,
        "month": month,
        "zip_sha256": sha256_bytes(payload),
        "csv_member": member,
        "csv_sha256": sha256_bytes(csv_bytes),
        "csv_schema_variant": schema_variant,
        "completion_evidence": completion_evidence,
        "rows": len(rows),
        "first_open_time_ms": int(frame["open_time"].min()),
        "last_open_time_ms": int(frame["open_time"].max()),
    }
    return rows, audit


def load_core_and_features(core_path: Path, feature_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    verify_sha(core_path, EXPECTED_CORE_SHA256, "P0-A core")
    verify_sha(feature_path, EXPECTED_FEATURE_SHA256, "P0-A feature")
    core = pd.read_parquet(core_path, columns=["event_id", "asset", "decision_ts_utc"])
    feature = pd.read_parquet(
        feature_path,
        columns=[
            "event_id", "decision_ts_utc", "feature_end_minute_utc",
            "feature_available_ts_utc", *PARITY_COLUMNS,
        ],
    )
    core = core.copy()
    core["asset"] = core["asset"].astype(str).str.upper()
    core["decision_ts_utc"] = pd.to_datetime(core["decision_ts_utc"], utc=True)
    core = core.sort_values(["decision_ts_utc", "event_id"], kind="stable").reset_index(drop=True)
    if len(core) != EXPECTED_EVENTS or core["event_id"].duplicated().any():
        raise ValueError("P0-A core identity mismatch")
    if core["asset"].value_counts().to_dict() != EXPECTED_ASSET_COUNTS:
        raise ValueError("P0-A asset counts mismatch")

    feature = feature.copy().set_index("event_id")
    if any(eid not in feature.index for eid in core["event_id"]):
        raise ValueError("P0-A feature missing event")
    feature = feature.loc[core["event_id"].tolist()].reset_index()
    for col in ("decision_ts_utc", "feature_end_minute_utc", "feature_available_ts_utc"):
        feature[col] = pd.to_datetime(feature[col], utc=True, errors="coerce")
    if feature[["decision_ts_utc", "feature_end_minute_utc", "feature_available_ts_utc"]].isna().any().any():
        raise ValueError("P0-A feature clock invalid")
    if not feature["decision_ts_utc"].reset_index(drop=True).equals(core["decision_ts_utc"]):
        raise ValueError("P0-A core/feature decision clocks differ")
    return core, feature


def target_required_ms(target: str, events: pd.DataFrame) -> dict[str, set[int]]:
    required: dict[str, set[int]] = {"BTC": set(), "ETH": set()}
    if target == "dir014":
        for row in events.itertuples(index=False):
            asset = str(row.asset).upper()
            end = pd.Timestamp(row.decision_ts_utc).floor("min") - pd.Timedelta(minutes=1)
            start = end - pd.Timedelta(minutes=1440)
            for ts in pd.date_range(start, end, freq="1min", tz="UTC"):
                required[asset].add(int(ts.value // 1_000_000))
    elif target == "dir016":
        for row in events.itertuples(index=False):
            asset = str(row.asset).upper()
            current_hour = pd.Timestamp(row.decision_ts_utc).floor("h")
            for ts in pd.date_range(
                current_hour - pd.Timedelta(hours=1),
                current_hour - pd.Timedelta(minutes=1),
                freq="1min",
                tz="UTC",
            ):
                required[asset].add(int(ts.value // 1_000_000))
    else:
        raise ValueError(target)
    return required


def parity_required_ms(feature: pd.DataFrame, core: pd.DataFrame) -> dict[str, set[int]]:
    required: dict[str, set[int]] = {"BTC": set(), "ETH": set()}
    asset_by_id = dict(zip(core["event_id"].astype(str), core["asset"].astype(str)))
    for row in feature.itertuples(index=False):
        asset = asset_by_id[str(row.event_id)]
        end = pd.Timestamp(row.feature_end_minute_utc)
        for ts in pd.date_range(end - pd.Timedelta(minutes=240), end, freq="1min", tz="UTC"):
            required[asset].add(int(ts.value // 1_000_000))
    return required


def month_of_ms_utc8(ms: int) -> str:
    return (pd.to_datetime(ms, unit="ms", utc=True) + pd.Timedelta(hours=8)).strftime("%Y-%m")


def collect_provider_bars(
    *,
    labels: list[str],
    requested_ms: dict[str, set[int]],
    inventory_fetcher: Callable[[str, list[str]], list[dict[str, str]]] = fetch_inventory,
    downloader: Callable[[str], bytes] = download_archive,
) -> tuple[dict[str, pd.DataFrame], dict[str, str], list[dict[str, Any]], list[dict[str, Any]]]:
    label_set = set(labels)
    bars: dict[str, pd.DataFrame] = {}
    provider_sha: dict[str, str] = {}
    all_inventory: list[dict[str, Any]] = []
    all_audits: list[dict[str, Any]] = []

    for asset in ("BTC", "ETH"):
        inventory = inventory_fetcher(asset, labels)
        selected: dict[int, tuple[float, float, float, float]] = {}
        evidence: list[dict[str, Any]] = []
        for record in inventory:
            payload = downloader(record["url"])
            rows, audit = parse_archive(payload, asset=asset, month=record["month"])
            needed = requested_ms[asset]
            for ts_ms, values in rows.items():
                if ts_ms in needed:
                    prior = selected.get(ts_ms)
                    if prior is not None and prior != values:
                        raise ValueError(f"conflicting provider OHLC at {asset} {ts_ms}")
                    selected[ts_ms] = values
            evidence.append({
                "month": record["month"],
                "filename": record["filename"],
                "url": record["url"],
                "zip_sha256": audit["zip_sha256"],
                "csv_sha256": audit["csv_sha256"],
                "csv_schema_variant": audit["csv_schema_variant"],
            })
            all_audits.append({**record, **audit})
        if [row["month"] for row in inventory] != labels:
            raise ValueError(f"{asset} inventory month order drift")
        for ms in selected:
            if month_of_ms_utc8(ms) not in label_set:
                raise ValueError("selected provider minute outside admitted archive months")
        provider_sha[asset] = canonical_json_sha256(evidence)
        frame = pd.DataFrame(
            [
                {
                    "source_minute_utc": pd.to_datetime(ms, unit="ms", utc=True),
                    "open": values[0],
                    "high": values[1],
                    "low": values[2],
                    "close": values[3],
                }
                for ms, values in sorted(selected.items())
            ]
        )
        if frame.empty:
            frame = pd.DataFrame(columns=["source_minute_utc", *OHLC])
        frame = frame.set_index(pd.DatetimeIndex(frame.pop("source_minute_utc"), name="source_minute_utc"))
        bars[asset] = frame
        all_inventory.extend(inventory)
    return bars, provider_sha, all_inventory, all_audits


def float_bits(value: float) -> bytes:
    return struct.pack(">d", float(value))


def compute_p0a_primitives(rows: pd.DataFrame) -> dict[str, float]:
    if len(rows) != 241 or rows[OHLC].isna().any().any():
        raise ValueError("P0-A parity requires exactly 241 complete rows")
    open_ = rows["open"].to_numpy(dtype=float)
    high = rows["high"].to_numpy(dtype=float)
    low = rows["low"].to_numpy(dtype=float)
    close = rows["close"].to_numpy(dtype=float)
    if not all(_valid_ohlc(*values) for values in zip(open_, high, low, close)):
        raise ValueError("P0-A parity received invalid OHLC")

    ret_240 = (close[-1] / close[0] - 1.0) * 10000.0
    logret = np.diff(np.log(close))
    rv_240 = float(np.std(logret, ddof=1) * math.sqrt(len(logret)) * 10000.0)
    feature_open = open_[1:]
    feature_high = high[1:]
    feature_low = low[1:]
    feature_close = close[1:]
    last = float(feature_close[-1])
    mean = float(feature_close.mean())
    max_high = float(np.max(feature_high))
    min_low = float(np.min(feature_low))
    terminal_span = float(feature_high[-1] - feature_low[-1])
    body = (feature_close[-1] / feature_open[-1] - 1.0) * 10000.0
    range_bp = (feature_high[-1] / feature_low[-1] - 1.0) * 10000.0
    if terminal_span > 0.0:
        upper = (feature_high[-1] - max(feature_open[-1], feature_close[-1])) / terminal_span
        lower = (min(feature_open[-1], feature_close[-1]) - feature_low[-1]) / terminal_span
        close_loc = (feature_close[-1] - feature_low[-1]) / terminal_span
    else:
        upper, lower, close_loc = 0.0, 0.0, 0.5
    return {
        "ret_240m_bp": float(ret_240),
        "rv_240m_bp": float(rv_240),
        "ma_distance_240m_bp": float((last / mean - 1.0) * 10000.0),
        "drawdown_from_high_240m_bp": float((last / max_high - 1.0) * 10000.0),
        "runup_from_low_240m_bp": float((last / min_low - 1.0) * 10000.0),
        "high_low_range_240m_bp": float((max_high / min_low - 1.0) * 10000.0),
        "last_bar_body_bp": float(body),
        "last_bar_range_bp": float(range_bp),
        "last_bar_upper_wick_ratio": float(upper),
        "last_bar_lower_wick_ratio": float(lower),
        "last_bar_close_location": float(close_loc),
    }


def audit_overlap_parity(
    core: pd.DataFrame,
    feature: pd.DataFrame,
    bars: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    asset_by_id = dict(zip(core["event_id"].astype(str), core["asset"].astype(str)))
    compared_events = 0
    compared_values = 0
    for row in feature.itertuples(index=False):
        event_id = str(row.event_id)
        asset = asset_by_id[event_id]
        end = pd.Timestamp(row.feature_end_minute_utc)
        expected_index = pd.date_range(end - pd.Timedelta(minutes=240), end, freq="1min", tz="UTC")
        candidate = bars[asset].reindex(expected_index)
        if candidate[OHLC].isna().any().any():
            continue
        observed = compute_p0a_primitives(candidate)
        for column in PARITY_COLUMNS:
            expected = float(getattr(row, column))
            got = float(observed[column])
            compared_values += 1
            if float_bits(expected) != float_bits(got):
                raise ValueError(
                    f"P0-A provider overlap parity mismatch: {event_id} {column} "
                    f"{expected!r} != {got!r}"
                )
        compared_events += 1
    if compared_events <= 0:
        raise ValueError("provider overlap parity has zero comparable events")
    return {
        "overlap_parity_status": "PASS",
        "overlap_rows_compared": compared_events,
        "overlap_float64_values_compared": compared_values,
        "overlap_parity_columns": list(PARITY_COLUMNS),
        "overlap_equality": "IEEE754_FLOAT64_BIT_EXACT",
    }


def requested_range_digest(
    target: str,
    labels: list[str],
    target_ms: dict[str, set[int]],
    parity_ms: dict[str, set[int]],
) -> str:
    payload = {
        "target": target,
        "months": labels,
        "assets": {
            asset: {
                "target_count": len(target_ms[asset]),
                "target_min_ms": min(target_ms[asset]),
                "target_max_ms": max(target_ms[asset]),
                "parity_count": len(parity_ms[asset]),
                "parity_min_ms": min(parity_ms[asset]),
                "parity_max_ms": max(parity_ms[asset]),
            }
            for asset in ("BTC", "ETH")
        },
    }
    return canonical_json_sha256(payload)


def missing_digest(
    requested: dict[str, set[int]],
    bars: dict[str, pd.DataFrame],
) -> tuple[str, int]:
    lines: list[str] = []
    for asset in ("BTC", "ETH"):
        present = {int(ts.value // 1_000_000) for ts in bars[asset].index}
        for ms in sorted(requested[asset] - present):
            lines.append(f"{asset}|{ms}\n")
    return sha256_bytes("".join(lines).encode("utf-8")), len(lines)


def provider_provenance(
    target: str,
    labels: list[str],
    *,
    requested_sha: str,
    inventory_sha: str,
    missing_sha: str,
    parity: dict[str, Any],
) -> dict[str, Any]:
    start, end, count = TARGETS[target]["months"]
    if labels != month_labels(start, end, count):
        raise ValueError("provider month lattice drift")
    payload = {
        "provider": "OKX",
        "endpoint_family": BULK_PATH,
        "module": "2",
        "module_semantics": "1-minute candlestick",
        "inst_type": "SWAP",
        "inst_family_list": ["BTC-USDT", "ETH-USDT"],
        "date_aggregation": "monthly",
        "archive_calendar": "UTC+08:00",
        "archive_url_source": "OFFICIAL_ENDPOINT_RESPONSE_ONLY",
        "required_month_start": start,
        "required_month_end": end,
        "required_month_count": count,
        "completed_only": "official historical module=2 archive; no live/incomplete bars",
        "research_fields": OHLC,
        "clock": "UTC minute",
        "missingness": "explicit missing; no fill/interpolation",
        "requested_ranges_sha256": requested_sha,
        "retrieval_inventory_sha256": inventory_sha,
        "missing_minute_set_sha256": missing_sha,
        **parity,
    }
    return payload


def dir014_boundary_evidence(events: pd.DataFrame) -> dict[str, Any]:
    h = hashlib.sha256()
    required: dict[str, set[int]] = {"BTC": set(), "ETH": set()}
    for pos, row in enumerate(events.itertuples(index=False)):
        decision = pd.Timestamp(row.decision_ts_utc)
        end = decision.floor("min") - pd.Timedelta(minutes=1)
        start = end - pd.Timedelta(minutes=1440)
        line = (
            f"{pos}|{row.event_id}|{str(row.asset).upper()}|"
            f"{int(decision.value//1_000_000)}|{int(end.value//1_000_000)}|"
            f"{int(start.value//1_000_000)}|{int(end.value//1_000_000)}|1441"
        )
        h.update((line + "\n").encode())
        required[str(row.asset).upper()].update(
            range(int(start.value//1_000_000), int(end.value//1_000_000) + 60_000, 60_000)
        )
    counts = events["asset"].value_counts().to_dict()
    result = {
        "boundary_event_rows": len(events),
        "boundary_btc_events": int(counts.get("BTC", 0)),
        "boundary_eth_events": int(counts.get("ETH", 0)),
        "boundary_expected_rows_per_event": 1441,
        "boundary_total_logical_event_minutes": len(events) * 1441,
        "boundary_btc_union_minutes": len(required["BTC"]),
        "boundary_eth_union_minutes": len(required["ETH"]),
        "boundary_total_asset_union_minutes": len(required["BTC"]) + len(required["ETH"]),
        "boundary_sha256": h.hexdigest(),
    }
    if result != TARGETS["dir014"]["boundary"]:
        raise ValueError(f"DIR014 boundary evidence drift: {result!r}")
    return result


def dir016_clock_evidence(events: pd.DataFrame) -> dict[str, Any]:
    h = hashlib.sha256()
    physical: set[str] = set()
    rows = 0
    for pos, row in enumerate(events.itertuples(index=False)):
        decision = pd.Timestamp(row.decision_ts_utc)
        current = decision.floor("h")
        start = current - pd.Timedelta(hours=1)
        end = current - pd.Timedelta(minutes=1)
        asset = str(row.asset).upper()
        for offset in range(-60, 0):
            source = current + pd.Timedelta(minutes=offset)
            line = (
                f"{pos}|{row.event_id}|{asset}|{int(decision.value//1_000_000)}|"
                f"{int(current.value//1_000_000)}|{int(start.value//1_000_000)}|"
                f"{int(end.value//1_000_000)}|{offset}|{int(source.value//1_000_000)}"
            )
            h.update((line + "\n").encode())
            physical.add(f"{asset}|{int(source.value//1_000_000)}")
            rows += 1
    physical_bytes = "".join(f"{x}\n" for x in sorted(physical)).encode()
    counts = events["asset"].value_counts().to_dict()
    result = {
        "clock_events": len(events),
        "clock_btc_events": int(counts.get("BTC", 0)),
        "clock_eth_events": int(counts.get("ETH", 0)),
        "clock_ordered_rows": rows,
        "clock_unique_physical_asset_minutes": len(physical),
        "clock_ordered_sha256": h.hexdigest(),
        "clock_physical_source_key_sha256": sha256_bytes(physical_bytes),
    }
    if result != TARGETS["dir016"]["clock"]:
        raise ValueError(f"DIR016 clock evidence drift: {result!r}")
    return result


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.stem + "-", suffix=".json", dir=str(path.parent))
    os.close(fd)
    tmp = Path(temp)
    try:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def write_nonce_receipt(fixed: Path, run_dir: Path, nonce: int) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / f"{nonce}.json"
    if out.exists():
        raise FileExistsError(out)
    fd, temp = tempfile.mkstemp(prefix=f"{nonce}-", suffix=".json", dir=str(run_dir))
    os.close(fd)
    tmp = Path(temp)
    try:
        tmp.write_bytes(fixed.read_bytes())
        os.replace(tmp, out)
    finally:
        if tmp.exists():
            tmp.unlink()
    return out


def write_dir014(
    mod: Any,
    events: pd.DataFrame,
    bars: dict[str, pd.DataFrame],
    provider_sha: dict[str, str],
    out_dir: Path,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    source, windows = mod.export_union_slice(events, bars, source_sha256=provider_sha)
    records = mod.build_event_close_window_records(source, windows, source_sha256=provider_sha)
    out_dir.mkdir(parents=True, exist_ok=True)
    source_path = out_dir / "raw_24h_ohlc_union.parquet"
    windows_path = out_dir / "event_window_index.csv"
    event_path = out_dir / "event_close_windows.jsonl"
    manifest_path = out_dir / "raw_24h_source_manifest.json"
    source.to_parquet(source_path, index=False)
    windows.to_csv(windows_path, index=False)
    event_path.write_text(
        "".join(json.dumps(x, sort_keys=True, allow_nan=False) + "\n" for x in records),
        encoding="utf-8",
    )
    psha = canonical_json_sha256(provenance)
    manifest = {
        "schema_version": 2,
        "status": TARGETS["dir014"]["manifest_status"],
        "execution_mode": PROVIDER_MODE,
        "task_class": "GPT_SOURCE_RECONSTRUCTION",
        "transform_class": "DETERMINISTIC_UPSTREAM_REGENERATION",
        "semantic_owner": "GPT",
        "event_count": len(windows),
        "event_counts_by_asset": {str(k): int(v) for k, v in windows["asset"].value_counts().sort_index().items()},
        "window_returns": int(mod.WINDOW_RETURNS),
        "expected_rows_per_event": int(mod.EXPECTED_SOURCE_ROWS_PER_EVENT),
        "unique_source_rows": len(source),
        "unique_source_rows_by_asset": {str(k): int(v) for k, v in source["asset"].value_counts().sort_index().items()},
        "complete_events": int(windows["complete_window"].astype(bool).sum()),
        "incomplete_events": int((~windows["complete_window"].astype(bool)).sum()),
        "core_sha256": EXPECTED_CORE_SHA256,
        "lineage_reference_sha256": LINEAGE_REFERENCE_SHA256,
        "provider_provenance": provenance,
        "provider_provenance_sha256": psha,
        "provider_source_sha256": provider_sha,
        "source_union_sha256": sha256_file(source_path),
        "event_window_index_sha256": sha256_file(windows_path),
        "event_close_windows_sha256": sha256_file(event_path),
        "event_close_windows_rows": len(records),
        "event_close_window_observations": sum(len(x["close_pairs"]) for x in records),
        "event_close_windows_semantics": "exact_event_projection_of_observed_raw_close_values_with_existing_ohlc_coverage",
        "aggregation_performed": False,
        "research_features_computed": False,
        "returns_computed": False,
        "semivariance_computed": False,
        "outcome_table_opened": False,
        "statistical_inference_computed": False,
        "event_reselection_performed": False,
        "network_download_performed": True,
        "source_substitution_performed": False,
        "union_deduplication_only": True,
        "output_columns": list(source.columns),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "source_path": source_path, "availability_path": windows_path,
        "event_path": event_path, "manifest_path": manifest_path,
        "manifest": manifest,
    }


def write_dir016(
    mod: Any,
    events: pd.DataFrame,
    bars: dict[str, pd.DataFrame],
    provider_sha: dict[str, str],
    out_dir: Path,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    source, availability = mod.export_source_slice(events, bars, source_sha256=provider_sha)
    records = mod.build_event_window_records(source, availability, source_sha256=provider_sha)
    out_dir.mkdir(parents=True, exist_ok=True)
    source_path = out_dir / "prior_hour_ohlc_source_slice.parquet"
    availability_path = out_dir / "prior_hour_source_availability.csv"
    event_path = out_dir / "event_windows.jsonl"
    manifest_path = out_dir / "prior_hour_source_manifest.json"
    source.to_parquet(source_path, index=False)
    availability.to_csv(availability_path, index=False)
    event_path.write_text(
        "".join(json.dumps(x, sort_keys=True, allow_nan=False) + "\n" for x in records),
        encoding="utf-8",
    )
    psha = canonical_json_sha256(provenance)
    manifest = {
        "schema_version": 2,
        "status": TARGETS["dir016"]["manifest_status"],
        "execution_mode": PROVIDER_MODE,
        "task_class": "GPT_SOURCE_RECONSTRUCTION",
        "transform_class": "DETERMINISTIC_UPSTREAM_REGENERATION",
        "semantic_owner": "GPT",
        "event_count": len(availability),
        "event_counts_by_asset": {str(k): int(v) for k, v in availability["asset"].value_counts().sort_index().items()},
        "expected_rows_per_event": int(mod.EXPECTED_MINUTES),
        "source_rows": len(source),
        "complete_events": int(availability["complete_window"].astype(bool).sum()),
        "incomplete_events": int((~availability["complete_window"].astype(bool)).sum()),
        "core_sha256": EXPECTED_CORE_SHA256,
        "lineage_reference_sha256": LINEAGE_REFERENCE_SHA256,
        "provider_provenance": provenance,
        "provider_provenance_sha256": psha,
        "provider_source_sha256": provider_sha,
        "source_slice_sha256": sha256_file(source_path),
        "source_availability_sha256": sha256_file(availability_path),
        "event_windows_sha256": sha256_file(event_path),
        "event_windows_rows": len(records),
        "event_windows_source_rows": sum(len(x["rows"]) for x in records),
        "event_windows_semantics": "lossless_event_grouping_of_prior_hour_raw_ohlc_source_slice",
        "aggregation_performed": False,
        "research_features_computed": False,
        "returns_computed": False,
        "wick_computed": False,
        "outcome_table_opened": False,
        "statistical_inference_computed": False,
        "event_reselection_performed": False,
        "network_download_performed": True,
        "source_substitution_performed": False,
        "output_columns": list(source.columns),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "source_path": source_path, "availability_path": availability_path,
        "event_path": event_path, "manifest_path": manifest_path,
        "manifest": manifest,
    }


def main() -> None:
    args = parse_args()
    target = args.target
    config = TARGETS[target]
    core_path = resolve(args.core)
    feature_path = resolve(args.features)
    core, feature = load_core_and_features(core_path, feature_path)

    exporter_path = resolve(config["exporter"])
    if git_blob_sha(exporter_path) != config["exporter_blob"]:
        raise ValueError("frozen source exporter Git blob drift")
    mod = load_module(exporter_path, f"w7017_{target}_source_exporter")
    events = mod.load_events(core_path)

    labels = month_labels(*config["months"])
    target_ms = target_required_ms(target, core)
    parity_ms = parity_required_ms(feature, core)
    admitted_ms: dict[str, set[int]] = {"BTC": set(), "ETH": set()}
    label_set = set(labels)
    for asset in ("BTC", "ETH"):
        admitted_ms[asset] = set(target_ms[asset])
        admitted_ms[asset].update(
            ms for ms in parity_ms[asset] if month_of_ms_utc8(ms) in label_set
        )

    bars, provider_sha, inventory, audits = collect_provider_bars(
        labels=labels, requested_ms=admitted_ms
    )
    parity = audit_overlap_parity(core, feature, bars)
    requested_sha = requested_range_digest(target, labels, target_ms, parity_ms)
    inventory_sha = canonical_json_sha256({
        "inventory": inventory,
        "archive_audits": audits,
    })
    missing_sha, missing_count = missing_digest(admitted_ms, bars)
    provenance = provider_provenance(
        target,
        labels,
        requested_sha=requested_sha,
        inventory_sha=inventory_sha,
        missing_sha=missing_sha,
        parity=parity,
    )
    provenance["requested_provider_minutes"] = {
        asset: len(admitted_ms[asset]) for asset in ("BTC", "ETH")
    }
    provenance["missing_provider_minutes"] = missing_count
    provenance["archive_count"] = len(audits)

    out_dir = resolve(args.out_dir or config["out_dir"])
    if target == "dir014":
        evidence = dir014_boundary_evidence(events)
        outputs = write_dir014(mod, events, bars, provider_sha, out_dir, provenance)
    else:
        evidence = dir016_clock_evidence(events)
        outputs = write_dir016(mod, events, bars, provider_sha, out_dir, provenance)

    manifest_path = outputs["manifest_path"]
    psha = canonical_json_sha256(provenance)
    nonce = time.time_ns()
    receipt: dict[str, Any] = {
        "schema_version": 2,
        "status": "PASS",
        "task_id": config["task_id"],
        "execution_mode": PROVIDER_MODE,
        "executor_agent": "GPT",
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "attempt_nonce_ns": nonce,
        "core_sha256": EXPECTED_CORE_SHA256,
        "lineage_reference_sha256": LINEAGE_REFERENCE_SHA256,
        "provider_provenance": provenance,
        "provider_provenance_sha256": psha,
        "provider_source_sha256": provider_sha,
        "network_access": True,
        "market_download_performed": True,
        "source_substitution_performed": False,
        "feature_engineering_performed": False,
        "future_outcomes_opened": False,
        "statistical_inference_computed": False,
        "event_reselection_performed": False,
        "research_semantics_changed": False,
        **evidence,
    }
    if target == "dir014":
        receipt.update({
            "raw_24h_ohlc_union_sha256": sha256_file(outputs["source_path"]),
            "event_window_index_sha256": sha256_file(outputs["availability_path"]),
            "event_close_windows_sha256": sha256_file(outputs["event_path"]),
            "manifest_sha256": sha256_file(manifest_path),
            "returns_computed": False,
            "semivariance_computed": False,
        })
    else:
        receipt.update({
            "source_slice_sha256": sha256_file(outputs["source_path"]),
            "source_availability_sha256": sha256_file(outputs["availability_path"]),
            "event_windows_sha256": sha256_file(outputs["event_path"]),
            "manifest_sha256": sha256_file(manifest_path),
            "wick_computed": False,
        })

    fixed = resolve(config["receipt"])
    atomic_json(fixed, receipt)
    nonce_path = write_nonce_receipt(fixed, resolve(config["receipt_runs"]), nonce)
    if nonce_path.read_bytes() != fixed.read_bytes():
        raise RuntimeError("nonce receipt byte identity failed")

    print(json.dumps({
        "status": "PASS",
        "target": target,
        "execution_mode": PROVIDER_MODE,
        "provider_provenance_sha256": psha,
        "provider_source_sha256": provider_sha,
        "overlap_rows_compared": parity["overlap_rows_compared"],
        "missing_provider_minutes": missing_count,
        "receipt": str(fixed),
        "nonce_receipt": str(nonce_path),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
