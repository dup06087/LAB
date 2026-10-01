from __future__ import annotations

import importlib.util
import io
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "archive_source",
    ROOT / "scripts" / "collect_w3405_dir018_020_binance_archive_source.py",
)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def _zip_csv(lines: list[str]) -> bytes:
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("BTCUSDT-5m-test.csv", "\n".join(lines) + "\n")
    return bio.getvalue()


def _row(ot: int, close: str = "101.0") -> str:
    ct = ot + m.INTERVAL_MS - 1
    return f"{ot},100.0,102.0,99.0,{close},0,{ct},0,0,0,0,0"


def test_expected_bar_is_immediately_preceding_completed_5m() -> None:
    assert m.expected_open_ms(pd.Timestamp("2024-10-01T01:13:02Z")) == int(
        pd.Timestamp("2024-10-01T01:05:00Z").timestamp() * 1000
    )
    assert m.expected_close_ms(pd.Timestamp("2024-10-01T01:13:02Z")) == int(
        pd.Timestamp("2024-10-01T01:09:59.999Z").timestamp() * 1000
    )
    # Exact boundary still selects the preceding bar, never the just-opening bar.
    assert m.expected_open_ms(pd.Timestamp("2024-10-01T01:10:00Z")) == int(
        pd.Timestamp("2024-10-01T01:05:00Z").timestamp() * 1000
    )


def test_official_archive_path_is_frozen_to_um_monthly_5m() -> None:
    assert m.archive_relpath("premiumIndexKlines", "BTCUSDT", "2024-10") == (
        "data/futures/um/monthly/premiumIndexKlines/BTCUSDT/5m/BTCUSDT-5m-2024-10.zip"
    )
    assert m.archive_relpath("markPriceKlines", "ETHUSDT", "2026-03").endswith(
        "/markPriceKlines/ETHUSDT/5m/ETHUSDT-5m-2026-03.zip"
    )


def test_extract_exact_rows_never_uses_nearest_or_fill() -> None:
    a = int(pd.Timestamp("2024-10-01T01:05:00Z").timestamp() * 1000)
    b = a + m.INTERVAL_MS
    payload = _zip_csv(["open_time,open,high,low,close,volume,close_time", _row(a)])
    out = m.extract_expected_rows(payload, {a, b})
    assert out[a]["status"] == "ROW_FOUND"
    assert out[a]["raw_row"][0] == str(a)
    assert out[b]["status"] == "ROW_MISSING"
    assert out[b]["raw_row"] is None


def test_identical_duplicates_are_preserved_but_conflicting_duplicates_fail_closed() -> None:
    a = int(pd.Timestamp("2024-10-01T01:05:00Z").timestamp() * 1000)
    identical = m.extract_expected_rows(_zip_csv([_row(a), _row(a)]), {a})
    assert identical[a]["status"] == "ROW_FOUND"
    assert identical[a]["duplicate_count"] == 2

    conflict = m.extract_expected_rows(_zip_csv([_row(a, "101.0"), _row(a, "101.5")]), {a})
    assert conflict[a]["status"] == "CONFLICTING_DUPLICATE_OPEN_TIME"
    assert conflict[a]["raw_row"] is None


def test_malformed_exact_row_is_not_repaired() -> None:
    a = int(pd.Timestamp("2024-10-01T01:05:00Z").timestamp() * 1000)
    bad_close_time = a + m.INTERVAL_MS - 2
    payload = _zip_csv([f"{a},100,102,99,101,0,{bad_close_time},0"])
    out = m.extract_expected_rows(payload, {a})
    assert out[a]["status"] == "MALFORMED_EXACT_ROW"


def test_checksum_parser_binds_filename_when_present() -> None:
    digest = "a" * 64
    assert m.parse_checksum(
        f"{digest}  BTCUSDT-5m-2024-10.zip\n".encode(),
        "BTCUSDT-5m-2024-10.zip",
    ) == digest
