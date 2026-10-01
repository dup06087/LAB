#!/usr/bin/env python3
"""Outcome-blind admission audit for the distinct Binance archive lineage.

This script verifies only source execution provenance, archive checksum lineage,
frozen event identity, expected 5m clocks, source-status coverage and HOLD-mask
hashes for W3405-DIR-018/020.  It deliberately does not compute either
direction feature, assign actions, read outcomes, run inference or economics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "data/direction_event_ledger/p0a_ohlcv/direction_event_core.parquet"
DIR018_ROOT = ROOT / "data/direction_idea_bank/w3405_dir018_archive_reconstruction"
DIR020_ROOT = ROOT / "data/direction_idea_bank/w3405_dir020_archive_reconstruction"
ROWS018 = DIR018_ROOT / "source_rows.jsonl"
MAN018 = DIR018_ROOT / "manifest.json"
ROWS020 = DIR020_ROOT / "source_rows.jsonl"
MAN020 = DIR020_ROOT / "manifest.json"
SOURCE_TASK = ROOT / "control_plane/tasks/worker4638-w3405-dir018-020-binance-archive-source-reconstruction-codex-20260930.json"
SOURCE_TASK_ID = "worker4638-w3405-dir018-020-binance-archive-source-reconstruction-codex-20260930"
RECEIPT = ROOT / "artifacts/control_plane/w3405_dir018_020_binance_archive_collection_run_receipt_20260930.json"
RECEIPT_RUNS = ROOT / "artifacts/control_plane/w3405_dir018_020_binance_archive_collection_run_receipt_runs"
DEFAULT_OUT = ROOT / "research/W3405_DIR018_020_BINANCE_ARCHIVE_SOURCE_ADMISSION_WORKER4638_20260930.json"

CORE_SHA256 = "13bbd824115d023cdc8c98a3aa596c70d1e037af779d3c314dc76f6ea3bc41ad"
COLLECTOR_BLOB = "8350104ea0763003a5ff0d1935ec44d7996a2325"
COLLECTOR_TEST_BLOB = "1ba83fb44a5b4881032f7ffd00c3bc726d6a3b2b"
SOURCE_ROOT = "https://data.binance.vision/"
EXPECTED_EVENTS = 1147
EXPECTED_BY_ASSET = {"BTC": 535, "ETH": 612}
SYMBOLS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}
INTERVAL_MS = 300_000
ALLOWED_STATUS = {
    "ROW_FOUND",
    "ROW_MISSING",
    "ARCHIVE_OBJECT_NOT_FOUND",
    "CONFLICTING_DUPLICATE_OPEN_TIME",
    "MALFORMED_EXACT_ROW",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sha256_json(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(body).hexdigest()


def decision_ms(value: Any) -> int:
    ts = pd.Timestamp(value)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return int(ts.value // 1_000_000)


def iso_utc(value: Any) -> str:
    ts = pd.Timestamp(value)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return ts.isoformat().replace("+00:00", "Z")


def expected_open_ms(value: Any) -> int:
    ms = decision_ms(value)
    return (ms // INTERVAL_MS) * INTERVAL_MS - INTERVAL_MS


def expected_close_ms(value: Any) -> int:
    return expected_open_ms(value) + INTERVAL_MS - 1


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception as exc:
            raise ValueError(f"{path}: malformed JSON line {line_no}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"{path}: JSON line {line_no} is not an object")
        rows.append(row)
    return rows


def load_core(path: Path) -> pd.DataFrame:
    if sha256_file(path) != CORE_SHA256:
        raise ValueError("P0-A core SHA mismatch")
    core = pd.read_parquet(path, columns=["event_id", "asset", "decision_ts_utc"])
    core["event_id"] = core["event_id"].astype(str)
    core["asset"] = core["asset"].astype(str).str.upper()
    core["decision_ts_utc"] = pd.to_datetime(core["decision_ts_utc"], utc=True, errors="raise")
    if len(core) != EXPECTED_EVENTS or core["event_id"].duplicated().any():
        raise ValueError("P0-A event identity mismatch")
    if core["asset"].value_counts().to_dict() != EXPECTED_BY_ASSET:
        raise ValueError("P0-A asset counts mismatch")
    return core.reset_index(drop=True)


def verify_source_execution(
    *,
    task_path: Path = SOURCE_TASK,
    receipt_path: Path = RECEIPT,
    receipt_runs: Path = RECEIPT_RUNS,
    rows018: Path = ROWS018,
    man018: Path = MAN018,
    rows020: Path = ROWS020,
    man020: Path = MAN020,
) -> dict[str, Any]:
    for path in (task_path, receipt_path, rows018, man018, rows020, man020):
        if not path.is_file():
            raise FileNotFoundError(path)

    task = json.loads(task_path.read_text(encoding="utf-8"))
    if task.get("task_id") != SOURCE_TASK_ID:
        raise ValueError("archive source task id mismatch")
    if task.get("status") != "DONE":
        raise ValueError("archive source task not DONE")
    if task.get("responsible_agent") != "GPT":
        raise ValueError("archive source task responsible_agent mismatch")
    if task.get("execution_model") != "GPT_DIRECT_LAB_ACTIONS_NO_LOCAL_CODEX":
        raise ValueError("archive source task execution_model mismatch")
    if task.get("execution_engine") != "LAB_ACTIONS_PUBLIC_NETWORK_COLLECTION":
        raise ValueError("archive source task execution_engine mismatch")
    exact = task.get("exact_inputs") or {}
    required_exact = {
        "core_sha256": CORE_SHA256,
        "collector_blob": COLLECTOR_BLOB,
        "test_blob": COLLECTOR_TEST_BLOB,
        "source_root": SOURCE_ROOT,
        "source_lineage": "BINANCE_OFFICIAL_PUBLIC_DATA_ARCHIVE",
        "market": "um",
        "interval": "5m",
        "events": EXPECTED_EVENTS,
        "asset_counts": EXPECTED_BY_ASSET,
    }
    for key, expected in required_exact.items():
        if exact.get(key) != expected:
            raise ValueError(f"archive source task {key} mismatch")

    receipt_bytes = receipt_path.read_bytes()
    receipt = json.loads(receipt_bytes.decode("utf-8"))
    required_receipt = {
        "status": "PASS",
        "task_id": SOURCE_TASK_ID,
        "collector_blob": COLLECTOR_BLOB,
        "test_blob": COLLECTOR_TEST_BLOB,
        "core_sha256": CORE_SHA256,
        "source_root": SOURCE_ROOT,
        "credentials_used": False,
        "test_passed": True,
        "event_rows": EXPECTED_EVENTS,
        "btc_events": EXPECTED_BY_ASSET["BTC"],
        "eth_events": EXPECTED_BY_ASSET["ETH"],
        "source_lineage": "BINANCE_OFFICIAL_PUBLIC_DATA_ARCHIVE",
        "source_substitution_performed": True,
        "relative_to_original_fapi_task": True,
        "exact_expected_open_time_only": True,
        "nearest_asof_ffill_interpolation_performed": False,
        "archive_checksum_inventory_verified": True,
        "execution_engine": "LAB_ACTIONS_PUBLIC_NETWORK_COLLECTION",
        "feature_engineering_performed": False,
        "action_assigned": False,
        "future_outcomes_opened": False,
        "statistical_inference_computed": False,
        "economic_evaluation_performed": False,
        "event_reselection_performed": False,
        "research_semantics_changed": False,
    }
    for key, expected in required_receipt.items():
        if receipt.get(key) != expected:
            raise ValueError(f"archive source receipt {key} mismatch")
    if not isinstance(receipt.get("workflow_run_id"), int) or receipt["workflow_run_id"] <= 0:
        raise ValueError("archive source receipt workflow_run_id invalid")
    if not isinstance(receipt.get("workflow_artifact_id"), int) or receipt["workflow_artifact_id"] <= 0:
        raise ValueError("archive source receipt workflow_artifact_id invalid")
    head = str(receipt.get("workflow_head_sha") or "")
    if len(head) != 40 or any(ch not in "0123456789abcdef" for ch in head.lower()):
        raise ValueError("archive source receipt workflow_head_sha invalid")

    current = {
        "dir018_source_rows_sha256": sha256_file(rows018),
        "dir018_manifest_sha256": sha256_file(man018),
        "dir020_source_rows_sha256": sha256_file(rows020),
        "dir020_manifest_sha256": sha256_file(man020),
    }
    for key, expected in current.items():
        if receipt.get(key) != expected:
            raise ValueError(f"archive source receipt {key} drift")

    nonce = receipt.get("attempt_nonce_ns")
    if not isinstance(nonce, int) or nonce <= 0:
        raise ValueError("archive source receipt nonce invalid")
    nonce_path = receipt_runs / f"{nonce}.json"
    if not nonce_path.is_file():
        raise FileNotFoundError(nonce_path)
    if nonce_path.read_bytes() != receipt_bytes:
        raise ValueError("archive source nonce receipt mismatch")

    return {
        "source_task_id": SOURCE_TASK_ID,
        "source_execution_receipt_sha256": sha256_file(receipt_path),
        "attempt_nonce_ns": nonce,
        "nonce_receipt_path": nonce_path.as_posix(),
        **current,
    }


def verify_manifest(path: Path, rows_path: Path, idea: str) -> tuple[dict[str, Any], set[str]]:
    m = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "status": f"W3405_{idea}_BINANCE_OFFICIAL_ARCHIVE_SOURCE_RECONSTRUCTION_COMPLETE",
        "semantic_owner": "GPT",
        "task_class": "NETWORK_COLLECTION",
        "transform_class": "COLLECTION",
        "source_lineage": "BINANCE_OFFICIAL_PUBLIC_DATA_ARCHIVE",
        "source_substitution_performed": True,
        "relative_to_original_fapi_task": True,
        "archive_base_url": SOURCE_ROOT,
        "archive_market": "um",
        "interval": "5m",
        "core_sha256": CORE_SHA256,
        "event_rows": EXPECTED_EVENTS,
        "asset_event_rows": EXPECTED_BY_ASSET,
        "exact_expected_open_time_only": True,
        "nearest_asof_ffill_interpolation_performed": False,
        "feature_engineering_performed": False,
        "action_assigned": False,
        "outcome_table_read": False,
        "statistical_inference_computed": False,
        "economic_evaluation_performed": False,
        "event_reselection_performed": False,
    }
    for key, value in expected.items():
        if m.get(key) != value:
            raise ValueError(f"{idea} manifest {key} mismatch")
    if m.get("source_rows_sha256") != sha256_file(rows_path):
        raise ValueError(f"{idea} manifest source_rows_sha256 mismatch")

    inventory = m.get("object_inventory")
    if not isinstance(inventory, list) or not inventory:
        raise ValueError(f"{idea} manifest object_inventory missing")
    verified: set[str] = set()
    for item in inventory:
        if not isinstance(item, dict):
            raise ValueError(f"{idea} manifest bad inventory row")
        if item.get("status") == "VERIFIED":
            published = str(item.get("published_checksum_sha256") or "")
            downloaded = str(item.get("download_sha256") or "")
            if len(published) != 64 or published != downloaded:
                raise ValueError(f"{idea} archive checksum mismatch")
            verified.add(str(item.get("object_path") or ""))
    return m, verified


def _verify_leg(leg: Any, expected_kind: str, open_ms: int, close_ms: int, verified_objects: set[str]) -> str:
    if not isinstance(leg, dict):
        raise ValueError("archive source leg missing")
    if str(leg.get("source_kind") or "") != expected_kind:
        raise ValueError(f"archive source leg kind mismatch: expected {expected_kind}")
    if int(leg.get("expected_open_time_ms", -1)) != open_ms:
        raise ValueError("archive source leg open clock mismatch")
    if int(leg.get("expected_close_time_ms", -1)) != close_ms:
        raise ValueError("archive source leg close clock mismatch")
    status = str(leg.get("source_status") or "")
    if status not in ALLOWED_STATUS:
        raise ValueError(f"archive source status invalid: {status}")
    if status == "ROW_FOUND":
        object_path = str(leg.get("archive_object_path") or "")
        if object_path not in verified_objects:
            raise ValueError("ROW_FOUND references unverified archive object")
        raw = leg.get("raw_row")
        if not isinstance(raw, list) or len(raw) < 7:
            raise ValueError("ROW_FOUND missing raw row")
        if int(raw[0]) != open_ms or int(raw[6]) != close_ms:
            raise ValueError("ROW_FOUND raw timestamp mismatch")
    return status


def audit_rows(
    core: pd.DataFrame,
    rows018: list[dict[str, Any]],
    rows020: list[dict[str, Any]],
    verified018: set[str],
    verified020: set[str],
) -> dict[str, Any]:
    if len(rows018) != EXPECTED_EVENTS or len(rows020) != EXPECTED_EVENTS:
        raise ValueError("archive source event row count mismatch")

    status018: Counter[str] = Counter()
    mark_status: Counter[str] = Counter()
    index_status: Counter[str] = Counter()
    coverage018 = Counter()
    coverage020 = Counter()
    hold018: list[dict[str, Any]] = []
    hold020: list[dict[str, Any]] = []

    for i, core_row in enumerate(core.itertuples(index=False)):
        r18 = rows018[i]
        r20 = rows020[i]
        event_id = str(core_row.event_id)
        asset = str(core_row.asset).upper()
        decision = iso_utc(core_row.decision_ts_utc)
        symbol = SYMBOLS[asset]
        open_ms = expected_open_ms(core_row.decision_ts_utc)
        close_ms = open_ms + INTERVAL_MS - 1

        for rec, label in ((r18, "DIR018"), (r20, "DIR020")):
            if str(rec.get("event_id") or "") != event_id:
                raise ValueError(f"{label} event order/identity mismatch")
            if str(rec.get("asset") or "").upper() != asset:
                raise ValueError(f"{label} asset mismatch")
            if str(rec.get("source_symbol") or "") != symbol:
                raise ValueError(f"{label} symbol mismatch")
            if iso_utc(rec.get("decision_ts_utc")) != decision:
                raise ValueError(f"{label} decision clock mismatch")
            if int(rec.get("expected_open_time_ms", -1)) != open_ms:
                raise ValueError(f"{label} expected open mismatch")
            if int(rec.get("expected_close_time_ms", -1)) != close_ms:
                raise ValueError(f"{label} expected close mismatch")

        premium = _verify_leg(r18.get("premium"), "premiumIndexKlines", open_ms, close_ms, verified018)
        mark = _verify_leg(r20.get("mark"), "markPriceKlines", open_ms, close_ms, verified020)
        index = _verify_leg(r20.get("index"), "indexPriceKlines", open_ms, close_ms, verified020)
        status018[premium] += 1
        mark_status[mark] += 1
        index_status[index] += 1

        usable018 = premium == "ROW_FOUND"
        usable020 = mark == "ROW_FOUND" and index == "ROW_FOUND"
        coverage018[(asset, usable018)] += 1
        coverage020[(asset, usable020)] += 1
        hold018.append({"event_id": event_id, "hold": not usable018})
        hold020.append({"event_id": event_id, "hold": not usable020})

    return {
        "dir018": {
            "status_counts": dict(sorted(status018.items())),
            "coverage_by_asset": {
                asset: {
                    "usable": coverage018[(asset, True)],
                    "hold": coverage018[(asset, False)],
                }
                for asset in ("BTC", "ETH")
            },
            "hold_mask_sha256": sha256_json(hold018),
        },
        "dir020": {
            "mark_status_counts": dict(sorted(mark_status.items())),
            "index_status_counts": dict(sorted(index_status.items())),
            "coverage_by_asset": {
                asset: {
                    "usable": coverage020[(asset, True)],
                    "hold": coverage020[(asset, False)],
                }
                for asset in ("BTC", "ETH")
            },
            "hold_mask_sha256": sha256_json(hold020),
        },
    }


def run(
    *,
    core_path: Path = CORE,
    rows018_path: Path = ROWS018,
    man018_path: Path = MAN018,
    rows020_path: Path = ROWS020,
    man020_path: Path = MAN020,
    out_path: Path = DEFAULT_OUT,
) -> dict[str, Any]:
    execution = verify_source_execution(
        rows018=rows018_path,
        man018=man018_path,
        rows020=rows020_path,
        man020=man020_path,
    )
    core = load_core(core_path)
    _, verified018 = verify_manifest(man018_path, rows018_path, "DIR018")
    _, verified020 = verify_manifest(man020_path, rows020_path, "DIR020")
    rows018 = read_jsonl(rows018_path)
    rows020 = read_jsonl(rows020_path)
    coverage = audit_rows(core, rows018, rows020, verified018, verified020)

    result = {
        "schema_version": 1,
        "status": "PASS",
        "admission": "ARCHIVE_SOURCE_ADMISSION_READY_FOR_SEPARATE_GPT_SUCCESSOR_FEATURE_BUILD",
        "source_lineage": "BINANCE_OFFICIAL_PUBLIC_DATA_ARCHIVE",
        "source_substitution_performed": True,
        "relative_to_original_fapi_task": True,
        "event_rows": EXPECTED_EVENTS,
        "asset_event_rows": EXPECTED_BY_ASSET,
        "execution_provenance": execution,
        "coverage": coverage,
        "feature_engineering_performed": False,
        "action_assigned": False,
        "future_outcomes_opened": False,
        "statistical_inference_computed": False,
        "economic_evaluation_performed": False,
        "event_reselection_performed": False,
        "research_semantics_changed": False,
        "original_fapi_tasks_mutated": False,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return result


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--core", type=Path, default=CORE)
    p.add_argument("--dir018-rows", type=Path, default=ROWS018)
    p.add_argument("--dir018-manifest", type=Path, default=MAN018)
    p.add_argument("--dir020-rows", type=Path, default=ROWS020)
    p.add_argument("--dir020-manifest", type=Path, default=MAN020)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return p.parse_args()


def main() -> None:
    a = parse_args()
    result = run(
        core_path=a.core,
        rows018_path=a.dir018_rows,
        man018_path=a.dir018_manifest,
        rows020_path=a.dir020_rows,
        man020_path=a.dir020_manifest,
        out_path=a.out,
    )
    print(json.dumps({
        "status": result["status"],
        "admission": result["admission"],
        "out": str(a.out),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
