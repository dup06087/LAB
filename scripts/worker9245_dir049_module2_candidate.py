#!/usr/bin/env python3
from __future__ import annotations
import csv, gzip, hashlib, io, json, math, zipfile
from pathlib import Path
import pandas as pd

ART=Path("source.zip")
CLOCKS=Path("data/worker9245_dir049_frozen_clocks.csv")
OUT=Path("out")
EXPECTED_ART="1f948b39b1d4fc58fea5e8562543b91f995b323d6f5f1b826ec6e87d17a58aaa"
EXPECTED_GZ="593df1c696b9403432a5ecebc3943a931f63686fa4e390d50f9ff1bef38f84a4"
SLOT_SHA="63d9a39c70708d71f66e1098b9fb0bb29c26c08e1f5c72c5466fee3a6a801162"
UNIQUE_SHA="fedfd5816fdf3a505e7e1a582888586bb59feae1dd08fc882a39cfca4a66548c"

def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

if sha(ART)!=EXPECTED_ART:
    raise SystemExit("artifact sha drift")
with zipfile.ZipFile(ART) as z:
    if set(z.namelist())!={"manifest.json","okx_module2_1m_2024-09_2026-04.csv.gz"}:
        raise SystemExit("artifact members drift")
    manifest_bytes=z.read("manifest.json")
    gzip_bytes=z.read("okx_module2_1m_2024-09_2026-04.csv.gz")
if hashlib.sha256(gzip_bytes).hexdigest()!=EXPECTED_GZ:
    raise SystemExit("gzip sha drift")
source_manifest=json.loads(manifest_bytes)
for k,v in {"provider":"OKX","module":2,"date_aggregation":"monthly","month_start":"2024-09","month_end":"2026-04","month_count":20,"total_rows":1748160}.items():
    if source_manifest.get(k)!=v:
        raise SystemExit(f"source manifest {k} drift")

clocks=pd.read_csv(CLOCKS)
if len(clocks)!=535 or clocks["event_id"].duplicated().any():
    raise SystemExit("clock identity drift")
slot_hasher=hashlib.sha256()
required=set()
for pos,r in enumerate(clocks.itertuples(index=False)):
    for off in range(120):
        ms=int(r.feature_end_ms)-(119-off)*60000
        slot_hasher.update((f"{pos}|{r.event_id}|{int(r.decision_ms)}|{int(r.feature_end_ms)}|{int(r.feature_available_ms)}|{off}|{ms}\n").encode())
        required.add(ms)
unique_bytes="".join(f"{x}\n" for x in sorted(required)).encode()
if len(required)!=58216 or slot_hasher.hexdigest()!=SLOT_SHA or hashlib.sha256(unique_bytes).hexdigest()!=UNIQUE_SHA:
    raise SystemExit("clock digest drift")

found={}
prev=None
btc_rows=gaps=duplicates=invalid=0
with gzip.GzipFile(fileobj=io.BytesIO(gzip_bytes),mode="rb") as gz:
    reader=csv.DictReader(io.TextIOWrapper(gz,encoding="utf-8",newline=""))
    for row in reader:
        if row["asset"]!="BTC":
            continue
        if row["instrument"]!="BTC-USDT-SWAP":
            raise SystemExit("instrument drift")
        ts=int(row["open_time"])
        btc_rows+=1
        if prev is not None:
            delta=ts-prev
            if delta==0:
                duplicates+=1
            elif delta!=60000:
                gaps+=1
        prev=ts
        o,h,l,c,v=(float(row[x]) for x in ("open","high","low","close","volume"))
        if not (all(math.isfinite(x) for x in (o,h,l,c,v)) and min(o,h,l,c)>0 and h>=max(o,c,l) and l<=min(o,c,h) and v>=0):
            invalid+=1
        if ts in required:
            if ts in found:
                raise SystemExit(f"required duplicate {ts}")
            found[ts]=(o,h,l,c,v)
if (btc_rows,gaps,duplicates,invalid)!=(874080,0,0,0):
    raise SystemExit(f"BTC full-span integrity drift {(btc_rows,gaps,duplicates,invalid)}")
if len(found)!=58216:
    raise SystemExit(f"required minute coverage {len(found)}")

rows=[]
availability=[]
for pos,r in enumerate(clocks.itertuples(index=False)):
    start=int(r.feature_end_ms)-119*60000
    for off in range(120):
        ms=start+off*60000
        if ms not in found:
            raise SystemExit(f"missing required {r.event_id} {ms}")
        o,h,l,c,v=found[ms]
        rows.append({
            "event_id":str(r.event_id),
            "event_position":pos,
            "decision_ts_utc":pd.to_datetime(int(r.decision_ms),unit="ms",utc=True),
            "feature_end_minute_utc":pd.to_datetime(int(r.feature_end_ms),unit="ms",utc=True),
            "feature_available_ts_utc":pd.to_datetime(int(r.feature_available_ms),unit="ms",utc=True),
            "row_present":True,
            "window_offset":off,
            "source_minute_ts_utc":pd.to_datetime(ms,unit="ms",utc=True),
            "open":o,"high":h,"low":l,"close":c,"volume":v,
        })
    availability.append({
        "event_id":str(r.event_id),
        "event_position":pos,
        "decision_ts_utc":pd.to_datetime(int(r.decision_ms),unit="ms",utc=True),
        "feature_end_minute_utc":pd.to_datetime(int(r.feature_end_ms),unit="ms",utc=True),
        "feature_available_ts_utc":pd.to_datetime(int(r.feature_available_ms),unit="ms",utc=True),
        "window_start_minute_utc":pd.to_datetime(start,unit="ms",utc=True),
        "window_end_minute_utc":pd.to_datetime(int(r.feature_end_ms),unit="ms",utc=True),
        "expected_minutes":120,
        "present_timestamp_minutes":120,
        "missing_timestamp_minutes":0,
        "exact_timestamp_coverage":True,
    })
candidate=pd.DataFrame(rows)
availability=pd.DataFrame(availability)
if len(candidate)!=64200 or candidate["source_minute_ts_utc"].nunique()!=58216 or not candidate["row_present"].all() or len(availability)!=535:
    raise SystemExit("candidate shape drift")

OUT.mkdir(exist_ok=True)
source_path=OUT/"candidate_source_slice.parquet"
availability_path=OUT/"candidate_source_availability.csv"
manifest_path=OUT/"candidate_manifest.json"
candidate.to_parquet(source_path,index=False)
availability.to_csv(availability_path,index=False)
manifest={
    "schema_version":1,
    "status":"W1018_DIR049_PROVIDER_MODULE2_CANDLE_CANDIDATE_COMPLETE",
    "authoritative":False,
    "historical_parity_required":True,
    "source_substitution_admitted":False,
    "provider":"OKX",
    "instrument":"BTC-USDT-SWAP",
    "bar":"1m",
    "source_endpoint":"/api/v5/public/market-data-history",
    "source_module":2,
    "source_date_aggregation":"monthly",
    "source_month_start":"2024-09",
    "source_month_end":"2026-04",
    "source_workflow_repo":"dup06087/LAB",
    "source_workflow_run_id":36851531940,
    "source_artifact_id":11156111731,
    "source_artifact_zip_sha256":EXPECTED_ART,
    "source_gzip_sha256":EXPECTED_GZ,
    "source_decompressed_csv_sha256":"d25f511abca4da0e01004d9d09b3b569f56e2968e809b029cbd859661ffb937f",
    "source_workflow_blob":"2177b073861b955bc036d3fdc1e7472c5e877c32",
    "provider_output_volume_semantics":"RAW10 vol -> output volume; derivatives contract count",
    "events":535,
    "window_minutes":120,
    "slot_rows":64200,
    "candidate_minutes_present":58216,
    "candidate_minutes_missing":0,
    "complete_events":535,
    "clock_slot_sha256":SLOT_SHA,
    "clock_unique_source_minute_sha256":UNIQUE_SHA,
    "candidate_source_slice_sha256":sha(source_path),
    "candidate_source_availability_sha256":sha(availability_path),
    "feature_values_opened":False,
    "future_outcomes_opened":False,
    "event_reselection":False,
    "research_semantics_changed":False,
}
manifest_path.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n",encoding="utf-8")
print(json.dumps({"status":"PASS","source_sha256":manifest["candidate_source_slice_sha256"],"availability_sha256":manifest["candidate_source_availability_sha256"]},sort_keys=True))
