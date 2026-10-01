from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "audit_w3405_dir018_020_binance_archive_source.py"
SPEC = importlib.util.spec_from_file_location("archive_admission", MODULE_PATH)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def _execution_fixture(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(m, "EXPECTED_EVENTS", 2)
    monkeypatch.setattr(m, "EXPECTED_BY_ASSET", {"BTC": 1, "ETH": 1})

    rows18 = _write(tmp_path / "r18.jsonl", '{"x":1}\n')
    man18 = _write(tmp_path / "m18.json", '{"x":1}\n')
    rows20 = _write(tmp_path / "r20.jsonl", '{"x":1}\n')
    man20 = _write(tmp_path / "m20.json", '{"x":1}\n')

    task = tmp_path / "task.json"
    task.write_text(json.dumps({
        "task_id": m.SOURCE_TASK_ID,
        "status": "DONE",
        "responsible_agent": "GPT",
        "execution_model": "GPT_DIRECT_LAB_ACTIONS_NO_LOCAL_CODEX",
        "execution_engine": "LAB_ACTIONS_PUBLIC_NETWORK_COLLECTION",
        "exact_inputs": {
            "core_sha256": m.CORE_SHA256,
            "collector_blob": m.COLLECTOR_BLOB,
            "test_blob": m.COLLECTOR_TEST_BLOB,
            "source_root": m.SOURCE_ROOT,
            "source_lineage": "BINANCE_OFFICIAL_PUBLIC_DATA_ARCHIVE",
            "market": "um",
            "interval": "5m",
            "events": 2,
            "asset_counts": {"BTC": 1, "ETH": 1},
        },
    }), encoding="utf-8")

    receipt = tmp_path / "receipt.json"
    runs = tmp_path / "runs"
    runs.mkdir()
    payload = {
        "status": "PASS",
        "task_id": m.SOURCE_TASK_ID,
        "collector_blob": m.COLLECTOR_BLOB,
        "test_blob": m.COLLECTOR_TEST_BLOB,
        "core_sha256": m.CORE_SHA256,
        "source_root": m.SOURCE_ROOT,
        "credentials_used": False,
        "test_passed": True,
        "event_rows": 2,
        "btc_events": 1,
        "eth_events": 1,
        "source_lineage": "BINANCE_OFFICIAL_PUBLIC_DATA_ARCHIVE",
        "source_substitution_performed": True,
        "relative_to_original_fapi_task": True,
        "exact_expected_open_time_only": True,
        "nearest_asof_ffill_interpolation_performed": False,
        "archive_checksum_inventory_verified": True,
        "execution_engine": "LAB_ACTIONS_PUBLIC_NETWORK_COLLECTION",
        "workflow_run_id": 36865464876,
        "workflow_head_sha": "1a23c5faa7fb3a9377a14bc1d9b0b0f9a2d0489e",
        "workflow_artifact_id": 11163500840,
        "dir018_source_rows_sha256": m.sha256_file(rows18),
        "dir018_manifest_sha256": m.sha256_file(man18),
        "dir020_source_rows_sha256": m.sha256_file(rows20),
        "dir020_manifest_sha256": m.sha256_file(man20),
        "feature_engineering_performed": False,
        "action_assigned": False,
        "future_outcomes_opened": False,
        "statistical_inference_computed": False,
        "economic_evaluation_performed": False,
        "event_reselection_performed": False,
        "research_semantics_changed": False,
        "attempt_nonce_ns": 1802001,
    }
    receipt.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    (runs / "1802001.json").write_bytes(receipt.read_bytes())
    return task, receipt, runs, rows18, man18, rows20, man20


def test_source_execution_admits_exact_done_receipt(tmp_path: Path, monkeypatch):
    task, receipt, runs, r18, m18, r20, m20 = _execution_fixture(tmp_path, monkeypatch)
    got = m.verify_source_execution(
        task_path=task,
        receipt_path=receipt,
        receipt_runs=runs,
        rows018=r18,
        man018=m18,
        rows020=r20,
        man020=m20,
    )
    assert got["attempt_nonce_ns"] == 1802001
    assert got["source_execution_receipt_sha256"] == m.sha256_file(receipt)


def test_source_execution_rejects_stale_codex_provenance(tmp_path: Path, monkeypatch):
    task, receipt, runs, r18, m18, r20, m20 = _execution_fixture(tmp_path, monkeypatch)
    payload = json.loads(task.read_text())
    payload["responsible_agent"] = "CODEX"
    task.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="responsible_agent mismatch"):
        m.verify_source_execution(
            task_path=task, receipt_path=receipt, receipt_runs=runs,
            rows018=r18, man018=m18, rows020=r20, man020=m20,
        )


def test_source_execution_rejects_wrong_lab_engine(tmp_path: Path, monkeypatch):
    task, receipt, runs, r18, m18, r20, m20 = _execution_fixture(tmp_path, monkeypatch)
    payload = json.loads(task.read_text())
    payload["execution_engine"] = "GITHUB_ACTIONS_PUBLIC_NETWORK_COLLECTION"
    task.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="execution_engine mismatch"):
        m.verify_source_execution(
            task_path=task, receipt_path=receipt, receipt_runs=runs,
            rows018=r18, man018=m18, rows020=r20, man020=m20,
        )


def test_source_execution_rejects_not_done_task(tmp_path: Path, monkeypatch):
    task, receipt, runs, r18, m18, r20, m20 = _execution_fixture(tmp_path, monkeypatch)
    payload = json.loads(task.read_text())
    payload["status"] = "PENDING"
    task.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="source task not DONE"):
        m.verify_source_execution(
            task_path=task, receipt_path=receipt, receipt_runs=runs,
            rows018=r18, man018=m18, rows020=r20, man020=m20,
        )


def test_source_execution_rejects_current_file_drift(tmp_path: Path, monkeypatch):
    task, receipt, runs, r18, m18, r20, m20 = _execution_fixture(tmp_path, monkeypatch)
    r20.write_text('{"mutated":true}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="dir020_source_rows_sha256 drift"):
        m.verify_source_execution(
            task_path=task, receipt_path=receipt, receipt_runs=runs,
            rows018=r18, man018=m18, rows020=r20, man020=m20,
        )


def test_source_execution_rejects_nonce_mismatch(tmp_path: Path, monkeypatch):
    task, receipt, runs, r18, m18, r20, m20 = _execution_fixture(tmp_path, monkeypatch)
    (runs / "1802001.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="nonce receipt mismatch"):
        m.verify_source_execution(
            task_path=task, receipt_path=receipt, receipt_runs=runs,
            rows018=r18, man018=m18, rows020=r20, man020=m20,
        )


def _leg(kind: str, object_path: str, open_ms: int, close_ms: int, status: str):
    return {
        "source_kind": kind,
        "archive_object_path": object_path,
        "archive_checksum_path": object_path + ".CHECKSUM",
        "expected_open_time_ms": open_ms,
        "expected_close_time_ms": close_ms,
        "source_status": status,
        "duplicate_count": 0,
        "csv_member": "x.csv",
        "raw_row": [str(open_ms), "100", "102", "99", "101", "0", str(close_ms)]
        if status == "ROW_FOUND" else None,
    }


def _core_and_rows(monkeypatch):
    monkeypatch.setattr(m, "EXPECTED_EVENTS", 2)
    monkeypatch.setattr(m, "EXPECTED_BY_ASSET", {"BTC": 1, "ETH": 1})
    core = pd.DataFrame([
        {"event_id": "e1", "asset": "BTC", "decision_ts_utc": pd.Timestamp("2026-01-03T12:34:56Z")},
        {"event_id": "e2", "asset": "ETH", "decision_ts_utc": pd.Timestamp("2026-01-04T00:02:00Z")},
    ])
    rows18 = []
    rows20 = []
    for i, row in core.iterrows():
        asset = row["asset"]
        symbol = m.SYMBOLS[asset]
        ot = m.expected_open_ms(row["decision_ts_utc"])
        ct = ot + m.INTERVAL_MS - 1
        base = {
            "event_id": row["event_id"],
            "asset": asset,
            "source_symbol": symbol,
            "decision_ts_utc": m.iso_utc(row["decision_ts_utc"]),
            "expected_open_time_ms": ot,
            "expected_close_time_ms": ct,
        }
        p_obj = f"p/{asset}.zip"
        m_obj = f"m/{asset}.zip"
        i_obj = f"i/{asset}.zip"
        p_status = "ROW_FOUND" if i == 0 else "ROW_MISSING"
        rows18.append({**base, "premium": _leg("premiumIndexKlines", p_obj, ot, ct, p_status)})
        rows20.append({
            **base,
            "mark": _leg("markPriceKlines", m_obj, ot, ct, "ROW_FOUND"),
            "index": _leg("indexPriceKlines", i_obj, ot, ct, "ROW_FOUND" if i == 0 else "ROW_MISSING"),
        })
    verified18 = {"p/BTC.zip", "p/ETH.zip"}
    verified20 = {"m/BTC.zip", "m/ETH.zip", "i/BTC.zip", "i/ETH.zip"}
    return core, rows18, rows20, verified18, verified20


def test_audit_rows_freezes_coverage_and_hold_masks(monkeypatch):
    core, rows18, rows20, v18, v20 = _core_and_rows(monkeypatch)
    got = m.audit_rows(core, rows18, rows20, v18, v20)
    assert got["dir018"]["coverage_by_asset"] == {
        "BTC": {"usable": 1, "hold": 0},
        "ETH": {"usable": 0, "hold": 1},
    }
    assert got["dir020"]["coverage_by_asset"] == {
        "BTC": {"usable": 1, "hold": 0},
        "ETH": {"usable": 0, "hold": 1},
    }
    assert len(got["dir018"]["hold_mask_sha256"]) == 64
    assert len(got["dir020"]["hold_mask_sha256"]) == 64


def test_audit_rows_rejects_event_clock_mismatch(monkeypatch):
    core, rows18, rows20, v18, v20 = _core_and_rows(monkeypatch)
    rows20[0]["expected_open_time_ms"] += m.INTERVAL_MS
    with pytest.raises(ValueError, match="DIR020 expected open mismatch"):
        m.audit_rows(core, rows18, rows20, v18, v20)


def test_row_found_requires_verified_archive_object(monkeypatch):
    core, rows18, rows20, v18, v20 = _core_and_rows(monkeypatch)
    with pytest.raises(ValueError, match="unverified archive object"):
        m.audit_rows(core, rows18, rows20, set(), v20)


def test_audit_rows_rejects_source_kind_impersonation(monkeypatch):
    core, rows18, rows20, v18, v20 = _core_and_rows(monkeypatch)
    rows18[0]["premium"]["source_kind"] = "markPriceKlines"
    with pytest.raises(ValueError, match="leg kind mismatch"):
        m.audit_rows(core, rows18, rows20, v18, v20)


def test_verify_manifest_rejects_bad_published_checksum(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(m, "EXPECTED_EVENTS", 2)
    monkeypatch.setattr(m, "EXPECTED_BY_ASSET", {"BTC": 1, "ETH": 1})
    rows = _write(tmp_path / "rows.jsonl", '{"x":1}\n')
    manifest = {
        "status": "W3405_DIR018_BINANCE_OFFICIAL_ARCHIVE_SOURCE_RECONSTRUCTION_COMPLETE",
        "semantic_owner": "GPT",
        "task_class": "NETWORK_COLLECTION",
        "transform_class": "COLLECTION",
        "source_lineage": "BINANCE_OFFICIAL_PUBLIC_DATA_ARCHIVE",
        "source_substitution_performed": True,
        "relative_to_original_fapi_task": True,
        "archive_base_url": m.SOURCE_ROOT,
        "archive_market": "um",
        "interval": "5m",
        "core_sha256": m.CORE_SHA256,
        "event_rows": 2,
        "asset_event_rows": {"BTC": 1, "ETH": 1},
        "exact_expected_open_time_only": True,
        "nearest_asof_ffill_interpolation_performed": False,
        "feature_engineering_performed": False,
        "action_assigned": False,
        "outcome_table_read": False,
        "statistical_inference_computed": False,
        "economic_evaluation_performed": False,
        "event_reselection_performed": False,
        "source_rows_sha256": m.sha256_file(rows),
        "object_inventory": [{
            "status": "VERIFIED",
            "object_path": "x.zip",
            "published_checksum_sha256": "a" * 64,
            "download_sha256": "b" * 64,
        }],
    }
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="archive checksum mismatch"):
        m.verify_manifest(p, rows, "DIR018")


def test_validator_contains_no_outcome_table_path_or_feature_formula():
    src = MODULE_PATH.read_text(encoding="utf-8")
    assert "direction_outcome" not in src
    assert "acceptance_gap" not in src
    assert "upper_rej" not in src
