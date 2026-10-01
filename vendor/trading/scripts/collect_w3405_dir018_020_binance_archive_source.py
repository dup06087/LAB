#!/usr/bin/env python3
"""Outcome-blind official Binance archive source reconstruction for W3405-DIR-018/020.

This is a NEW source lineage. It never impersonates the frozen fapi raw-response
collectors and never computes direction features/actions or reads outcomes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

CORE_SHA256 = "13bbd824115d023cdc8c98a3aa596c70d1e037af779d3c314dc76f6ea3bc41ad"
BASE_URL = "https://data.binance.vision/"
INTERVAL = "5m"
INTERVAL_MS = 300_000
EXPECTED_EVENTS = 1147
EXPECTED_BY_ASSET = {"BTC": 535, "ETH": 612}
SYMBOLS = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}
KINDS = ("premiumIndexKlines", "markPriceKlines", "indexPriceKlines")
OFFICIAL_REPO = "binance/binance-public-data"
OFFICIAL_BLOBS = {
    "README": "77671f0b61ae35f3de9d7d8aed0b8370c1ca12c4",
    "premiumIndexKlines": "74bfae744bce78f99fc675cf6788a417b3795a9b",
    "markPriceKlines": "d1a2bf34441951d2e711a3729911f1292a2d75c0",
    "indexPriceKlines": "b432c4cd334dc86b52eda6e6968fe067fe86f17b",
    "utility": "72d3ee62cd727bfbfc412783d65a7dca151f1773",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def iso_utc(value: Any) -> str:
    ts = pd.Timestamp(value)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return ts.isoformat().replace("+00:00", "Z")


def decision_ms(value: Any) -> int:
    ts = pd.Timestamp(value)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return int(ts.value // 1_000_000)


def expected_open_ms(value: Any) -> int:
    """Immediately preceding fully completed 5m bar."""
    ms = decision_ms(value)
    return (ms // INTERVAL_MS) * INTERVAL_MS - INTERVAL_MS


def expected_close_ms(value: Any) -> int:
    return expected_open_ms(value) + INTERVAL_MS - 1


def month_key(open_ms: int) -> str:
    return pd.to_datetime(open_ms, unit="ms", utc=True).strftime("%Y-%m")


def archive_relpath(kind: str, symbol: str, ym: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"unsupported kind: {kind}")
    return (
        f"data/futures/um/monthly/{kind}/{symbol.upper()}/{INTERVAL}/"
        f"{symbol.upper()}-{INTERVAL}-{ym}.zip"
    )


def checksum_relpath(kind: str, symbol: str, ym: str) -> str:
    return archive_relpath(kind, symbol, ym) + ".CHECKSUM"


def parse_checksum(body: bytes, expected_filename: str) -> str:
    text = body.decode("utf-8").strip()
    if not text:
        raise ValueError("empty checksum body")
    first = text.splitlines()[0].strip().split()
    if not first or len(first[0]) != 64:
        raise ValueError("malformed checksum")
    digest = first[0].lower()
    int(digest, 16)
    if len(first) >= 2:
        name = first[-1].lstrip("*")
        if name and Path(name).name != expected_filename:
            raise ValueError(f"checksum filename mismatch: {name} != {expected_filename}")
    return digest


def fetch_bytes(url: str, timeout: float, retries: int) -> tuple[bytes | None, str]:
    last: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={"User-Agent": "dup06087-trading-archive-source/1"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = int(getattr(resp, "status", 200))
                body = resp.read()
            if status != 200:
                raise RuntimeError(f"HTTP {status}")
            return body, "OK"
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None, "HTTP_404"
            last = exc
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            last = exc
        if attempt < retries:
            time.sleep(min(2.0, 0.25 * (2**attempt)))
    raise RuntimeError(f"network fetch failed: {url}") from last


def _row_signature(row: list[str]) -> str:
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"))


def extract_expected_rows(zip_bytes: bytes, expected_opens: set[int]) -> dict[int, dict[str, Any]]:
    """Extract only requested open times; never choose nearest or fill gaps."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        members = [n for n in zf.namelist() if not n.endswith("/") and n.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError(f"expected exactly one CSV member, got {members!r}")
        member = members[0]
        grouped: dict[int, list[list[str]]] = defaultdict(list)
        with zf.open(member) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            for row in csv.reader(text):
                if not row:
                    continue
                try:
                    ot = int(row[0])
                except Exception:
                    # Some archive variants may carry one header line.
                    continue
                if ot not in expected_opens:
                    continue
                if len(row) < 7:
                    grouped[ot].append(row)
                    continue
                grouped[ot].append(row)

    out: dict[int, dict[str, Any]] = {}
    for ot in expected_opens:
        rows = grouped.get(ot, [])
        if not rows:
            out[ot] = {"status": "ROW_MISSING", "raw_row": None, "duplicate_count": 0, "csv_member": member}
            continue
        sigs = {_row_signature(r) for r in rows}
        if len(sigs) > 1:
            out[ot] = {
                "status": "CONFLICTING_DUPLICATE_OPEN_TIME",
                "raw_row": None,
                "duplicate_count": len(rows),
                "csv_member": member,
            }
            continue
        row = rows[0]
        try:
            ct = int(row[6])
            vals = [float(row[i]) for i in (1, 2, 3, 4)]
            if len(row) < 7 or ot % INTERVAL_MS != 0 or ct != ot + INTERVAL_MS - 1:
                raise ValueError
            if not all(math.isfinite(x) for x in vals):
                raise ValueError
        except Exception:
            out[ot] = {
                "status": "MALFORMED_EXACT_ROW",
                "raw_row": row,
                "duplicate_count": len(rows),
                "csv_member": member,
            }
            continue
        out[ot] = {
            "status": "ROW_FOUND",
            "raw_row": row,
            "duplicate_count": len(rows),
            "csv_member": member,
        }
    return out


def load_core(path: Path) -> pd.DataFrame:
    digest = sha256_file(path)
    if digest != CORE_SHA256:
        raise ValueError(f"P0-A core SHA mismatch: {digest}")
    x = pd.read_parquet(path, columns=["event_id", "asset", "decision_ts_utc"])
    x["event_id"] = x["event_id"].astype(str)
    x["asset"] = x["asset"].astype(str).str.upper()
    x["decision_ts_utc"] = pd.to_datetime(x["decision_ts_utc"], utc=True, errors="raise")
    if len(x) != EXPECTED_EVENTS or x["event_id"].duplicated().any():
        raise ValueError("P0-A event identity mismatch")
    if x["asset"].value_counts().to_dict() != EXPECTED_BY_ASSET:
        raise ValueError("P0-A asset counts mismatch")
    return x.reset_index(drop=True)


def object_requirements(core: pd.DataFrame) -> dict[tuple[str, str, str], set[int]]:
    req: dict[tuple[str, str, str], set[int]] = defaultdict(set)
    for row in core.itertuples(index=False):
        symbol = SYMBOLS[str(row.asset)]
        ot = expected_open_ms(row.decision_ts_utc)
        ym = month_key(ot)
        for kind in KINDS:
            req[(kind, symbol, ym)].add(ot)
    return req


def collect_objects(
    requirements: dict[tuple[str, str, str], set[int]],
    timeout: float,
    retries: int,
) -> tuple[dict[tuple[str, str, str], dict[int, dict[str, Any]]], list[dict[str, Any]]]:
    extracted: dict[tuple[str, str, str], dict[int, dict[str, Any]]] = {}
    inventory: list[dict[str, Any]] = []
    for kind, symbol, ym in sorted(requirements):
        rel = archive_relpath(kind, symbol, ym)
        chk_rel = checksum_relpath(kind, symbol, ym)
        chk_body, chk_status = fetch_bytes(BASE_URL + chk_rel, timeout, retries)
        if chk_body is None:
            extracted[(kind, symbol, ym)] = {
                ot: {"status": "ARCHIVE_OBJECT_NOT_FOUND", "raw_row": None, "duplicate_count": 0, "csv_member": None}
                for ot in requirements[(kind, symbol, ym)]
            }
            inventory.append({"kind": kind, "symbol": symbol, "month": ym, "object_path": rel,
                              "checksum_path": chk_rel, "status": chk_status})
            continue
        expected_sha = parse_checksum(chk_body, Path(rel).name)
        zip_body, zip_status = fetch_bytes(BASE_URL + rel, timeout, retries)
        if zip_body is None:
            extracted[(kind, symbol, ym)] = {
                ot: {"status": "ARCHIVE_OBJECT_NOT_FOUND", "raw_row": None, "duplicate_count": 0, "csv_member": None}
                for ot in requirements[(kind, symbol, ym)]
            }
            inventory.append({"kind": kind, "symbol": symbol, "month": ym, "object_path": rel,
                              "checksum_path": chk_rel, "status": zip_status, "published_checksum_sha256": expected_sha})
            continue
        actual_sha = sha256_bytes(zip_body)
        if actual_sha != expected_sha:
            raise ValueError(f"archive checksum mismatch for {rel}: {actual_sha} != {expected_sha}")
        rows = extract_expected_rows(zip_body, requirements[(kind, symbol, ym)])
        extracted[(kind, symbol, ym)] = rows
        inventory.append({
            "kind": kind, "symbol": symbol, "month": ym, "object_path": rel, "checksum_path": chk_rel,
            "status": "VERIFIED", "published_checksum_sha256": expected_sha, "download_sha256": actual_sha,
            "zip_bytes": len(zip_body), "requested_open_times": len(requirements[(kind, symbol, ym)]),
            "row_status_counts": dict(sorted(Counter(v["status"] for v in rows.values()).items())),
        })
    return extracted, inventory


def leg(extracted: dict[tuple[str, str, str], dict[int, dict[str, Any]]], kind: str, symbol: str, ot: int) -> dict[str, Any]:
    ym = month_key(ot)
    rel = archive_relpath(kind, symbol, ym)
    row = extracted[(kind, symbol, ym)][ot]
    return {
        "source_kind": kind,
        "archive_object_path": rel,
        "archive_checksum_path": rel + ".CHECKSUM",
        "expected_open_time_ms": ot,
        "expected_close_time_ms": ot + INTERVAL_MS - 1,
        "source_status": row["status"],
        "duplicate_count": row["duplicate_count"],
        "csv_member": row["csv_member"],
        "raw_row": row["raw_row"],
    }


def build_records(core: pd.DataFrame, extracted: dict[tuple[str, str, str], dict[int, dict[str, Any]]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    d18: list[dict[str, Any]] = []
    d20: list[dict[str, Any]] = []
    for row in core.itertuples(index=False):
        asset = str(row.asset)
        symbol = SYMBOLS[asset]
        ot = expected_open_ms(row.decision_ts_utc)
        base = {
            "event_id": str(row.event_id),
            "asset": asset,
            "source_symbol": symbol,
            "decision_ts_utc": iso_utc(row.decision_ts_utc),
            "expected_open_time_ms": ot,
            "expected_close_time_ms": ot + INTERVAL_MS - 1,
        }
        d18.append({**base, "premium": leg(extracted, "premiumIndexKlines", symbol, ot)})
        d20.append({
            **base,
            "mark": leg(extracted, "markPriceKlines", symbol, ot),
            "index": leg(extracted, "indexPriceKlines", symbol, ot),
        })
    return d18, d20


def write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    tmp.replace(path)


def status_counts_d18(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(r["premium"]["source_status"] for r in rows).items()))


def status_counts_d20(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "mark": dict(sorted(Counter(r["mark"]["source_status"] for r in rows).items())),
        "index": dict(sorted(Counter(r["index"]["source_status"] for r in rows).items())),
        "both_found": sum(r["mark"]["source_status"] == "ROW_FOUND" and r["index"]["source_status"] == "ROW_FOUND" for r in rows),
    }


def manifest(kind: str, rows_path: Path, core: pd.DataFrame, inventory: list[dict[str, Any]], status: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": f"W3405_{kind}_BINANCE_OFFICIAL_ARCHIVE_SOURCE_RECONSTRUCTION_COMPLETE",
        "semantic_owner": "GPT",
        "task_class": "NETWORK_COLLECTION",
        "transform_class": "COLLECTION",
        "source_lineage": "BINANCE_OFFICIAL_PUBLIC_DATA_ARCHIVE",
        "source_substitution_performed": True,
        "relative_to_original_fapi_task": True,
        "official_repo": OFFICIAL_REPO,
        "official_repo_blobs": OFFICIAL_BLOBS,
        "archive_base_url": BASE_URL,
        "archive_market": "um",
        "interval": INTERVAL,
        "core_sha256": CORE_SHA256,
        "event_rows": len(core),
        "asset_event_rows": EXPECTED_BY_ASSET,
        "event_min_decision_ts_utc": iso_utc(core["decision_ts_utc"].min()),
        "event_max_decision_ts_utc": iso_utc(core["decision_ts_utc"].max()),
        "source_rows_path": rows_path.name,
        "source_rows_sha256": sha256_file(rows_path),
        "object_inventory": inventory,
        "event_source_status": status,
        "exact_expected_open_time_only": True,
        "nearest_asof_ffill_interpolation_performed": False,
        "feature_engineering_performed": False,
        "action_assigned": False,
        "outcome_table_read": False,
        "statistical_inference_computed": False,
        "economic_evaluation_performed": False,
        "event_reselection_performed": False,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--core", type=Path, required=True)
    p.add_argument("--out-root", type=Path, required=True)
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--retries", type=int, default=3)
    return p.parse_args()


def main() -> None:
    a = parse_args()
    core = load_core(a.core)
    req = object_requirements(core)
    extracted, inventory = collect_objects(req, a.timeout, a.retries)
    d18, d20 = build_records(core, extracted)

    root18 = a.out_root / "w3405_dir018_archive_reconstruction"
    root20 = a.out_root / "w3405_dir020_archive_reconstruction"
    rows18 = root18 / "source_rows.jsonl"
    rows20 = root20 / "source_rows.jsonl"
    write_jsonl_atomic(rows18, d18)
    write_jsonl_atomic(rows20, d20)

    m18 = manifest("DIR018", rows18, core, inventory, status_counts_d18(d18))
    m20 = manifest("DIR020", rows20, core, inventory, status_counts_d20(d20))
    (root18 / "manifest.json").write_text(json.dumps(m18, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    (root20 / "manifest.json").write_text(json.dumps(m20, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({"dir018": m18["event_source_status"], "dir020": m20["event_source_status"],
                      "objects": len(inventory)}, sort_keys=True))


if __name__ == "__main__":
    main()
