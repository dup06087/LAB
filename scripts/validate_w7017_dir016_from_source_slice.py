#!/usr/bin/env python3
"""GPT-owned W7017-DIR-016 validator using the shared raw source slice.

Research semantics remain identical to the frozen WORKER5300/WORKER1924 DIR-016
protocol. The neutral prior-hour OHLC source may come from authoritative OKX GPT
regeneration or the exact-local Codex fallback; this script admits that provenance
before wick feature construction, P0-A outcome join, inference, economics and verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "scripts/validate_w7017_dir016_completed_hour_wick.py"
DEFAULT_LEDGER = ROOT / "data/direction_event_ledger/p0a_ohlcv"
DEFAULT_SOURCE = ROOT / "data/direction_idea_bank/w7017_dir016/prior_hour_ohlc_source_slice.parquet"
DEFAULT_AVAILABILITY = ROOT / "data/direction_idea_bank/w7017_dir016/prior_hour_source_availability.csv"
DEFAULT_MANIFEST = ROOT / "data/direction_idea_bank/w7017_dir016/prior_hour_source_manifest.json"
DEFAULT_EVENT_WINDOWS = ROOT / "data/direction_idea_bank/w7017_dir016/event_windows.jsonl"
DEFAULT_OUT = ROOT / "research/W7017_DIR016_NUMERIC_DIRECTION_VALIDATION_WORKER5300_20260927.json"
SOURCE_TASK_ID = "worker5300-w7017-dir016-prior-hour-source-slice-codex-20260927"
SOURCE_TASK = ROOT / "control_plane/tasks/worker5300-w7017-dir016-prior-hour-source-slice-codex-20260927.json"
SOURCE_RECEIPT = ROOT / "artifacts/control_plane/w7017_dir016_source_export_run_receipt_20260930.json"
SOURCE_RECEIPT_RUNS = ROOT / "artifacts/control_plane/w7017_dir016_source_export_run_receipt_runs"
EXPECTED_SOURCE_EXPORTER_BLOB = "c02f63814768ee49233d50574b8ccc6eca83c4e8"
EXPECTED_SOURCE_EXPORTER_TEST_BLOB = "b4939828291e51524bfc8ce6393fa6be3f2efeff"

PROVIDER_MODE = "GPT_AUTHORITATIVE_OKX_UPSTREAM_REGENERATION"
FALLBACK_MODE = "EXACT_HASH_PINNED_LOCAL_BYTE_EXPORT"
EXPECTED_PROVIDER_PROVENANCE = {
    "provider": "OKX",
    "endpoint_family": "/api/v5/market/history-candles",
    "instruments": ["BTC-USDT-SWAP", "ETH-USDT-SWAP"],
    "bar": "1m",
    "completed_only": "confirm=1",
    "research_fields": ["open", "high", "low", "close"],
    "clock": "UTC minute",
    "missingness": "explicit missing; no fill/interpolation",
}
EXPECTED_BULK_PROVIDER_PROVENANCE = {
    "provider": "OKX",
    "endpoint_family": "/api/v5/public/market-data-history",
    "module": "2",
    "module_semantics": "1-minute candlestick",
    "inst_type": "SWAP",
    "inst_family_list": ["BTC-USDT", "ETH-USDT"],
    "date_aggregation": "monthly",
    "archive_calendar": "UTC+08:00",
    "archive_url_source": "OFFICIAL_ENDPOINT_RESPONSE_ONLY",
    "required_month_start": "2024-10",
    "required_month_end": "2026-04",
    "required_month_count": 19,
    "completed_only": "official historical module=2 archive; no live/incomplete bars",
    "research_fields": ["open", "high", "low", "close"],
    "clock": "UTC minute",
    "missingness": "explicit missing; no fill/interpolation",
}
PROVIDER_DIGEST_FIELDS = (
    "requested_ranges_sha256",
    "retrieval_inventory_sha256",
    "missing_minute_set_sha256",
)

EXPECTED_CORE_SHA256 = "13bbd824115d023cdc8c98a3aa596c70d1e037af779d3c314dc76f6ea3bc41ad"
EXPECTED_OUTCOME_SHA256 = "6e97adaeaa6605bdebc8d0a39c44f8cc42aa9be5bc85b009c71229098b75e3d9"
EXPECTED_RAW_SHA256 = {
    "BTC": "34fc490ff3df8bdf0d70d102d2acbe6576876353ce7c125ab623ce195ee31abc",
    "ETH": "6d090908df785ba77e85256bc324354fe6716823908306bedfa1ad1851c46809",
}
EXPECTED_LINEAGE_REFERENCE_SHA256 = {
    "p0a_core": EXPECTED_CORE_SHA256,
    "btc_1m": EXPECTED_RAW_SHA256["BTC"],
    "eth_1m": EXPECTED_RAW_SHA256["ETH"],
}
EXPECTED_EVENT_COUNTS = {"BTC": 535, "ETH": 612}
EXPECTED_EVENTS = 1147
CLOCK_RECEIPT_EXPECTED = {
    "clock_events": 1147,
    "clock_btc_events": 535,
    "clock_eth_events": 612,
    "clock_ordered_rows": 68820,
    "clock_unique_physical_asset_minutes": 65820,
    "clock_ordered_sha256": "78662ce9e7c295956582f104babd03fc57b117217b7cc86caa87cf8689346be9",
    "clock_physical_source_key_sha256": "229555bd1aa526800da419a93bfe1782383dac41872d648bbd3ab03b67b47c26",
}
OHLC = ["open", "high", "low", "close"]


def _load_base():
    spec = importlib.util.spec_from_file_location("dir016_frozen_base", BASE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import frozen DIR016 base validator")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BASE = _load_base()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ledger-root", type=Path, default=DEFAULT_LEDGER)
    p.add_argument("--source-slice", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--availability", type=Path, default=DEFAULT_AVAILABILITY)
    p.add_argument("--source-manifest", type=Path, default=DEFAULT_MANIFEST)
    p.add_argument("--event-windows", type=Path, default=DEFAULT_EVENT_WINDOWS)
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


def canonical_json_sha256(obj: Any) -> str:
    payload = json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_sha256_text(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


def _validate_asset_sha_map(payload: Any, label: str) -> dict[str, str]:
    if not isinstance(payload, dict) or set(payload) != {"BTC", "ETH"}:
        raise ValueError(f"{label} provider_source_sha256 keys mismatch")
    out = {str(k): str(v) for k, v in payload.items()}
    for asset, value in out.items():
        if not _is_sha256_text(value):
            raise ValueError(f"{label} provider_source_sha256 {asset} invalid")
    return out


def validate_provider_provenance(payload: Any, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{label} provider_provenance must be an object")
    endpoint = payload.get("endpoint_family")
    if endpoint == EXPECTED_PROVIDER_PROVENANCE["endpoint_family"]:
        expected = EXPECTED_PROVIDER_PROVENANCE
    elif endpoint == EXPECTED_BULK_PROVIDER_PROVENANCE["endpoint_family"]:
        expected = EXPECTED_BULK_PROVIDER_PROVENANCE
    else:
        raise ValueError(f"{label} provider provenance endpoint_family drift")
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(f"{label} provider provenance {key} drift")
    for key in PROVIDER_DIGEST_FIELDS:
        if not _is_sha256_text(payload.get(key)):
            raise ValueError(f"{label} provider provenance {key} invalid")
    if payload.get("overlap_parity_status") != "PASS":
        raise ValueError(f"{label} provider overlap parity must PASS")
    rows = payload.get("overlap_rows_compared")
    if isinstance(rows, bool) or not isinstance(rows, int) or rows <= 0:
        raise ValueError(f"{label} provider overlap PASS requires positive compared rows")
    return dict(payload)


def source_execution_mode(manifest: dict[str, Any]) -> str:
    mode = manifest.get("execution_mode") or FALLBACK_MODE
    if mode not in {PROVIDER_MODE, FALLBACK_MODE}:
        raise ValueError(f"unsupported DIR016 source execution mode: {mode!r}")
    return mode


def verify_source_execution(
    source_path: Path,
    availability_path: Path,
    manifest_path: Path,
    event_windows_path: Path,
    *,
    task_path: Path = SOURCE_TASK,
    receipt_path: Path = SOURCE_RECEIPT,
    receipt_runs: Path = SOURCE_RECEIPT_RUNS,
) -> dict[str, Any]:
    """Bind current DIR016 source bytes to one admitted provider/fallback execution."""
    for path in (
        source_path,
        availability_path,
        manifest_path,
        event_windows_path,
        task_path,
        receipt_path,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)

    task = json.loads(task_path.read_text(encoding="utf-8"))
    task_identity = task.get("task_id") or task.get("id")
    if task_identity != SOURCE_TASK_ID:
        raise ValueError("source task id mismatch")
    if task.get("status") != "DONE":
        raise ValueError("source task not DONE")
    if task.get("responsible_agent") != "GPT":
        raise ValueError("source task must remain GPT-owned")
    contract = task.get("provider_receipt_contract") or {}
    if contract.get("primary_execution_mode") != PROVIDER_MODE:
        raise ValueError("source task provider receipt mode contract drift")
    if contract.get("fallback_execution_mode") != FALLBACK_MODE:
        raise ValueError("source task fallback receipt mode contract drift")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_mode = source_execution_mode(manifest)

    receipt_bytes = receipt_path.read_bytes()
    receipt = json.loads(receipt_bytes.decode("utf-8"))
    if not isinstance(receipt, dict):
        raise ValueError("source receipt must be a JSON object")
    required = {
        "status": "PASS",
        "task_id": SOURCE_TASK_ID,
        "core_sha256": EXPECTED_CORE_SHA256,
        "feature_engineering_performed": False,
        "wick_computed": False,
        "future_outcomes_opened": False,
        "statistical_inference_computed": False,
        "event_reselection_performed": False,
        "research_semantics_changed": False,
        **CLOCK_RECEIPT_EXPECTED,
    }
    for key, expected in required.items():
        if receipt.get(key) != expected:
            raise ValueError(f"source receipt {key} mismatch")

    mode = receipt.get("execution_mode") or FALLBACK_MODE
    if mode != manifest_mode:
        raise ValueError("source receipt/manifest execution mode mismatch")

    current = {
        "source_slice_sha256": sha256_file(source_path),
        "source_availability_sha256": sha256_file(availability_path),
        "event_windows_sha256": sha256_file(event_windows_path),
        "manifest_sha256": sha256_file(manifest_path),
    }
    for key, expected in current.items():
        if receipt.get(key) != expected:
            raise ValueError(f"source receipt {key} drift")

    provider_provenance_sha256 = None
    provider_source_sha256 = None
    if mode == FALLBACK_MODE:
        pins = task.get("pinned_git_blobs") or {}
        if pins.get("exporter") != EXPECTED_SOURCE_EXPORTER_BLOB:
            raise ValueError("source task fallback exporter blob mismatch")
        if pins.get("test") != EXPECTED_SOURCE_EXPORTER_TEST_BLOB:
            raise ValueError("source task fallback test blob mismatch")
        executor_agent = receipt.get("executor_agent")
        if executor_agent not in (None, "CODEX"):
            raise ValueError("source fallback receipt executor mismatch")
        for key, expected in {
            "exporter_blob": EXPECTED_SOURCE_EXPORTER_BLOB,
            "test_blob": EXPECTED_SOURCE_EXPORTER_TEST_BLOB,
            "btc_1m_sha256": EXPECTED_RAW_SHA256["BTC"],
            "eth_1m_sha256": EXPECTED_RAW_SHA256["ETH"],
            "market_download_performed": False,
        }.items():
            if receipt.get(key) != expected:
                raise ValueError(f"source fallback receipt {key} mismatch")
    elif mode == PROVIDER_MODE:
        executor_agent = receipt.get("executor_agent")
        if executor_agent not in {"GPT", "CODEX"}:
            raise ValueError("source provider receipt executor must be GPT or delegated CODEX")
        if executor_agent == "CODEX":
            delegation = task.get("provider_network_execution_delegation") or {}
            expected_delegation = {
                "valid": True,
                "executor_agent": "CODEX",
                "minimum_boundary": "OFFICIAL_OKX_MODULE2_NETWORK_COLLECTION_AND_DETERMINISTIC_FROZEN_SOURCE_MATERIALIZATION",
                "network_only": True,
                "research_semantic_owner": "GPT",
                "source_substitution_allowed": False,
            }
            for key, expected in expected_delegation.items():
                if delegation.get(key) != expected:
                    raise ValueError(f"source provider CODEX delegation {key} mismatch")
            if receipt.get("execution_boundary") != "NETWORK_COLLECTION_ONLY":
                raise ValueError("source provider CODEX receipt execution boundary mismatch")
        elif receipt.get("execution_boundary") not in (None, "GPT_DIRECT_PROVIDER_REGENERATION"):
            raise ValueError("source provider GPT receipt execution boundary mismatch")
        if receipt.get("market_download_performed") is not True:
            raise ValueError("source provider receipt must assert market_download_performed=true")
        if receipt.get("source_substitution_performed") is not False:
            raise ValueError("source provider receipt must assert source_substitution_performed=false")
        if manifest.get("source_substitution_performed") is not False:
            raise ValueError("source provider manifest must assert source_substitution_performed=false")
        for payload, label in ((receipt, "receipt"), (manifest, "manifest")):
            if (payload.get("lineage_reference_sha256") or {}) != EXPECTED_LINEAGE_REFERENCE_SHA256:
                raise ValueError(f"{label} frozen lineage-reference hash drift")
        receipt_provider = validate_provider_provenance(receipt.get("provider_provenance"), "receipt")
        manifest_provider = validate_provider_provenance(manifest.get("provider_provenance"), "manifest")
        if receipt_provider != manifest_provider:
            raise ValueError("provider provenance differs across receipt/manifest")
        provider_provenance_sha256 = canonical_json_sha256(manifest_provider)
        if receipt.get("provider_provenance_sha256") != provider_provenance_sha256:
            raise ValueError("source provider provenance SHA mismatch")
        if manifest.get("provider_provenance_sha256") != provider_provenance_sha256:
            raise ValueError("source manifest provider provenance SHA mismatch")
        provider_source_sha256 = _validate_asset_sha_map(
            receipt.get("provider_source_sha256"), "receipt"
        )
        manifest_provider_source = _validate_asset_sha_map(
            manifest.get("provider_source_sha256"), "manifest"
        )
        if provider_source_sha256 != manifest_provider_source:
            raise ValueError("provider source SHA map differs across receipt/manifest")
    else:
        raise ValueError(f"unsupported source receipt execution mode: {mode!r}")

    nonce = receipt.get("attempt_nonce_ns")
    if isinstance(nonce, bool) or not isinstance(nonce, int) or nonce <= 0:
        raise ValueError("source receipt nonce invalid")
    nonce_path = receipt_runs / f"{nonce}.json"
    if not nonce_path.is_file():
        raise FileNotFoundError(nonce_path)
    if nonce_path.read_bytes() != receipt_bytes:
        raise ValueError("source nonce receipt mismatch")

    return {
        "source_task_id": SOURCE_TASK_ID,
        "source_task_status": "DONE",
        "source_execution_receipt_sha256": sha256_file(receipt_path),
        "source_attempt_nonce_ns": nonce,
        "source_nonce_receipt_path": nonce_path.as_posix(),
        "execution_mode": mode,
        "executor_agent": ("CODEX" if mode == FALLBACK_MODE else receipt.get("executor_agent")),
        "provider_provenance_sha256": provider_provenance_sha256,
        "provider_source_sha256": provider_source_sha256,
        **current,
        **{key: receipt[key] for key in CLOCK_RECEIPT_EXPECTED},
    }


def verify_source_bundle(
    source_path: Path,
    availability_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mode = source_execution_mode(manifest)
    if manifest.get("status") != "W7017_DIR016_PRIOR_HOUR_SOURCE_SLICE_EXPORT_COMPLETE":
        raise ValueError("source manifest status mismatch")
    if manifest.get("semantic_owner") != "GPT":
        raise ValueError("source manifest semantic_owner mismatch")

    false_fields = [
        "aggregation_performed",
        "research_features_computed",
        "returns_computed",
        "wick_computed",
        "outcome_table_opened",
        "statistical_inference_computed",
        "event_reselection_performed",
    ]
    bad = [key for key in false_fields if manifest.get(key) is not False]
    if bad:
        raise ValueError(f"source manifest semantic-boundary flags not false: {bad}")

    if int(manifest.get("event_count", -1)) != EXPECTED_EVENTS:
        raise ValueError("source manifest event count mismatch")
    if manifest.get("event_counts_by_asset") != EXPECTED_EVENT_COUNTS:
        raise ValueError("source manifest asset counts mismatch")
    if int(manifest.get("expected_rows_per_event", -1)) != 60:
        raise ValueError("source manifest expected_rows_per_event mismatch")

    provider_provenance_sha256 = None
    provider_source_sha256 = None
    if mode == FALLBACK_MODE:
        if manifest.get("task_class") != "LOCAL_SOURCE_EXPORT":
            raise ValueError("source fallback manifest task_class mismatch")
        if manifest.get("transform_class") != "SUBSET_EXPORT":
            raise ValueError("source fallback manifest transform_class mismatch")
        if manifest.get("network_download_performed") is not False:
            raise ValueError("source fallback manifest network_download_performed mismatch")
        if manifest.get("raw_source_sha256") != EXPECTED_RAW_SHA256:
            raise ValueError("source manifest raw source hash mismatch")
    elif mode == PROVIDER_MODE:
        if manifest.get("task_class") != "GPT_SOURCE_RECONSTRUCTION":
            raise ValueError("source provider manifest task_class mismatch")
        if manifest.get("transform_class") != "DETERMINISTIC_UPSTREAM_REGENERATION":
            raise ValueError("source provider manifest transform_class mismatch")
        if manifest.get("network_download_performed") is not True:
            raise ValueError("source provider manifest network_download_performed mismatch")
        if manifest.get("source_substitution_performed") is not False:
            raise ValueError("source provider manifest source_substitution_performed mismatch")
        if (manifest.get("lineage_reference_sha256") or {}) != EXPECTED_LINEAGE_REFERENCE_SHA256:
            raise ValueError("source provider manifest lineage-reference hash drift")
        provider = validate_provider_provenance(manifest.get("provider_provenance"), "manifest")
        provider_provenance_sha256 = canonical_json_sha256(provider)
        if manifest.get("provider_provenance_sha256") != provider_provenance_sha256:
            raise ValueError("source provider manifest provenance SHA mismatch")
        provider_source_sha256 = _validate_asset_sha_map(
            manifest.get("provider_source_sha256"), "manifest"
        )
    else:
        raise ValueError(f"unsupported source bundle execution mode: {mode!r}")

    source_hash = sha256_file(source_path)
    availability_hash = sha256_file(availability_path)
    if source_hash != manifest.get("source_slice_sha256"):
        raise ValueError("source slice hash mismatch")
    if availability_hash != manifest.get("source_availability_sha256"):
        raise ValueError("source availability hash mismatch")

    return {
        "execution_mode": mode,
        "source_manifest_sha256": sha256_file(manifest_path),
        "source_slice_sha256": source_hash,
        "source_availability_sha256": availability_hash,
        "raw_source_sha256": EXPECTED_RAW_SHA256 if mode == FALLBACK_MODE else None,
        "provider_provenance_sha256": provider_provenance_sha256,
        "provider_source_sha256": provider_source_sha256,
    }


def load_source_bundle(
    source_path: Path,
    availability_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    source = pd.read_parquet(source_path)
    availability = pd.read_csv(availability_path)

    required_source = {
        "event_id", "asset", "decision_ts_utc", "current_hour_start_utc",
        "source_hour_start_utc", "source_hour_end_utc", "source_minute_utc",
        "minute_offset", "open", "high", "low", "close", "source_sha256",
    }
    required_availability = {
        "event_id", "asset", "decision_ts_utc", "current_hour_start_utc",
        "source_hour_start_utc", "source_hour_end_utc", "expected_rows",
        "observed_rows", "valid_ohlc_rows", "complete_window", "missing_reason",
    }
    if required_source - set(source.columns):
        raise ValueError(f"source slice missing columns: {sorted(required_source-set(source.columns))}")
    if required_availability - set(availability.columns):
        raise ValueError(
            f"availability missing columns: {sorted(required_availability-set(availability.columns))}"
        )

    forbidden_tokens = (
        "return", "wick", "skew", "label", "action", "outcome", "future",
        "pnl", "profit", "bootstrap", "inference", "verdict",
    )
    forbidden = [c for c in source.columns if any(t in c.lower() for t in forbidden_tokens)]
    if forbidden:
        raise ValueError(f"source slice contains research-semantic columns: {forbidden}")

    for c in ["decision_ts_utc", "current_hour_start_utc", "source_hour_start_utc",
              "source_hour_end_utc", "source_minute_utc"]:
        source[c] = pd.to_datetime(source[c], utc=True, errors="coerce")
    for c in ["decision_ts_utc", "current_hour_start_utc", "source_hour_start_utc",
              "source_hour_end_utc"]:
        availability[c] = pd.to_datetime(availability[c], utc=True, errors="coerce")
    if source[["decision_ts_utc", "source_minute_utc"]].isna().any().any():
        raise ValueError("invalid source slice timestamp")
    if availability["decision_ts_utc"].isna().any():
        raise ValueError("invalid availability timestamp")

    if len(availability) != EXPECTED_EVENTS or availability["event_id"].duplicated().any():
        raise ValueError("availability event identity mismatch")
    counts = availability["asset"].astype(str).str.upper().value_counts().to_dict()
    if counts != EXPECTED_EVENT_COUNTS:
        raise ValueError(f"availability asset counts mismatch: {counts}")
    if not availability["expected_rows"].eq(60).all():
        raise ValueError("availability expected_rows must equal 60")

    if (source["source_minute_utc"] >= source["current_hour_start_utc"]).any():
        raise ValueError("source row reaches current event hour")
    if (source["current_hour_start_utc"] > source["decision_ts_utc"]).any():
        raise ValueError("current-hour start after decision")
    if source.duplicated(["event_id", "source_minute_utc"]).any():
        raise ValueError("duplicate event/minute in source slice")
    return source, availability


def build_feature_table_from_source(
    core: pd.DataFrame,
    source: pd.DataFrame,
    availability: pd.DataFrame,
    *,
    execution_mode: str = FALLBACK_MODE,
    provider_source_sha256: dict[str, str] | None = None,
) -> pd.DataFrame:
    if execution_mode == PROVIDER_MODE:
        provider_source_sha256 = _validate_asset_sha_map(
            provider_source_sha256, "feature source"
        )
    elif execution_mode != FALLBACK_MODE:
        raise ValueError(f"unsupported feature source execution mode: {execution_mode!r}")
    availability_by_id = availability.set_index("event_id", drop=False)
    source_groups = {str(k): g.copy() for k, g in source.groupby("event_id", sort=False)}
    rows: list[dict[str, Any]] = []

    for event in core.sort_values(["decision_ts_utc", "event_id"], kind="stable").itertuples(index=False):
        event_id = str(event.event_id)
        asset = str(event.asset).upper()
        if event_id not in availability_by_id.index:
            raise ValueError(f"missing availability row for {event_id}")
        a = availability_by_id.loc[event_id]
        if str(a["asset"]).upper() != asset:
            raise ValueError(f"asset mismatch for {event_id}")

        group = source_groups.get(event_id)
        if group is None or group.empty:
            bars = pd.DataFrame(columns=OHLC, index=pd.DatetimeIndex([], tz="UTC"))
        else:
            if set(group["asset"].astype(str).str.upper().unique()) != {asset}:
                raise ValueError(f"mixed asset source rows for {event_id}")
            expected_sha = (
                EXPECTED_RAW_SHA256[asset]
                if execution_mode == FALLBACK_MODE
                else provider_source_sha256[asset]
            )
            if set(group["source_sha256"].astype(str).unique()) != {expected_sha}:
                raise ValueError(f"source SHA mismatch within event {event_id}")
            bars = group.set_index("source_minute_utc")[OHLC].copy()
            bars = BASE.normalize_bars(bars)

        feature = BASE.prior_hour_feature(event.decision_ts_utc, bars)
        rows.append({
            "event_id": event_id,
            "asset": asset,
            "decision_ts_utc": pd.Timestamp(event.decision_ts_utc),
            **feature,
        })

        declared_complete = str(a["complete_window"]).strip().lower() in {"true", "1"}
        if declared_complete != bool(feature["feature_known"]):
            raise ValueError(
                f"source availability/feature validity mismatch for {event_id}: "
                f"declared_complete={declared_complete}, feature_known={feature['feature_known']}"
            )

    result = pd.DataFrame(rows)
    if len(result) != len(core) or result["event_id"].duplicated().any():
        raise RuntimeError("feature construction changed frozen event identity")
    return result


def main() -> None:
    a = parse_args()
    ledger = resolve(a.ledger_root)
    source_path = resolve(a.source_slice)
    availability_path = resolve(a.availability)
    manifest_path = resolve(a.source_manifest)
    event_windows_path = resolve(a.event_windows)
    out_path = resolve(a.out)

    core_path = ledger / "direction_event_core.parquet"
    outcome_path = ledger / "direction_outcome.parquet"
    if sha256_file(core_path) != EXPECTED_CORE_SHA256:
        raise ValueError("P0-A core SHA mismatch")

    source_execution = verify_source_execution(
        source_path, availability_path, manifest_path, event_windows_path
    )
    source_provenance = verify_source_bundle(source_path, availability_path, manifest_path)
    if source_provenance["execution_mode"] != source_execution["execution_mode"]:
        raise ValueError("source bundle/receipt execution mode mismatch")
    if source_provenance.get("provider_source_sha256") != source_execution.get("provider_source_sha256"):
        raise ValueError("source bundle/receipt provider source SHA mismatch")
    source_provenance.update(source_execution)
    source, availability = load_source_bundle(source_path, availability_path)

    core = pd.read_parquet(core_path)

    # Freeze the registered outcome-blind prior-hour wick feature, including the
    # source-availability/feature-validity consistency gate, before even
    # hashing/reading the future-outcome file.
    feature_table = build_feature_table_from_source(
        core,
        source,
        availability,
        execution_mode=source_provenance["execution_mode"],
        provider_source_sha256=source_provenance.get("provider_source_sha256"),
    )

    if sha256_file(outcome_path) != EXPECTED_OUTCOME_SHA256:
        raise ValueError("P0-A outcome SHA mismatch")
    outcomes = pd.read_parquet(outcome_path)
    result = BASE.run_validation(core, outcomes, feature_table)

    result["source_slice_provenance"] = source_provenance
    result["research_execution_owner"] = "GPT"
    result["source_materialization_owner"] = (
        "CODEX" if source_provenance["execution_mode"] == FALLBACK_MODE else "GPT"
    )
    result["local_source_export_owner"] = (
        "CODEX" if source_provenance["execution_mode"] == FALLBACK_MODE else None
    )
    result["semantic_boundary"] = (
        "EXACT_LOCAL_SOURCE_FALLBACK_ONLY__GPT_FEATURE_OUTCOME_JOIN_INFERENCE_ECONOMICS_VERDICT"
        if source_provenance["execution_mode"] == FALLBACK_MODE
        else "GPT_AUTHORITATIVE_OKX_SOURCE_REGENERATION__GPT_FEATURE_OUTCOME_JOIN_INFERENCE_ECONOMICS_VERDICT"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(BASE.json_ready(result), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "idea": result["idea"],
        "verdict": result["verdict"],
        "out": str(out_path),
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
