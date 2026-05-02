from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app

BASE_DIR = Path(__file__).resolve().parents[1]
DROPZONE = BASE_DIR / "github_data" / "dropzone"
OUT_DIR = BASE_DIR / "data" / "precomputed"


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=BASE_DIR, text=True).strip()
    except Exception:
        return None


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    drop_files = app.list_github_dropzone_files()
    parsed, warnings, failures = app.parse_dropzone_market_files(drop_files)

    assets = ["GER40", "UK100", "US30", "US500"]

    daily_rows, h4_attack_rows = [], []
    generic_rows, core_rows = [], []
    us4h_rows, h1_cont_rows = [], []

    for asset in assets:
        d1 = parsed.get(f"{asset}_1D")
        h1 = parsed.get(f"{asset}_1H")
        h4 = parsed.get(f"{asset}_4H")

        if d1 is not None:
            tbl = app.compute_daily_attack_stats(d1).copy()
            tbl.insert(0, "Asset", asset)
            daily_rows.append(tbl)

        if d1 is not None and h4 is not None:
            tbl, _dbg = app.compute_4h_attack_stats(d1, h4, asset)
            tbl.insert(0, "Asset", asset)
            h4_attack_rows.append(tbl)

        for tf, df in [("1H", h1), ("4H", h4)]:
            if df is None:
                continue
            tbl, _ = app.compute_sweep_stats(df)
            tbl = app.add_scenario_column(tbl, tf)
            tbl.insert(0, "Timeframe", tf)
            tbl.insert(0, "Asset", asset)
            generic_rows.append(tbl)

            mask = app.core_session_mask(df, asset, tf)
            core_df = df[mask].copy()
            if len(core_df):
                core_tbl, _ = app.compute_sweep_stats(core_df)
                core_tbl = app.add_scenario_column(core_tbl, tf, asset)
                core_tbl.insert(0, "Session", app.session_window_for_instrument(asset))
                core_tbl.insert(0, "Timeframe", tf)
                core_tbl.insert(0, "Asset", asset)
                core_rows.append(core_tbl)

        if h4 is not None and asset in {"US30", "US500"}:
            tbl, _dbg, _counts = app.compute_us_session_4h_sweep_edge(h4, asset)
            if not tbl.empty:
                us4h_rows.append(tbl)

    cont_tbl, _cont_dbg = app.compute_1h_daily_bias_continuation_sweep_edge(parsed)
    if not cont_tbl.empty:
        h1_cont_rows.append(cont_tbl)

    outputs = {
        "daily_attack_stats.csv": pd.concat(daily_rows, ignore_index=True) if daily_rows else pd.DataFrame(),
        "h4_daily_bias_attack_stats.csv": pd.concat(h4_attack_rows, ignore_index=True) if h4_attack_rows else pd.DataFrame(),
        "generic_sweep_stats.csv": pd.concat(generic_rows, ignore_index=True) if generic_rows else pd.DataFrame(),
        "core_session_sweep_stats.csv": pd.concat(core_rows, ignore_index=True) if core_rows else pd.DataFrame(),
        "us_session_4h_sweep_edge.csv": pd.concat(us4h_rows, ignore_index=True) if us4h_rows else pd.DataFrame(),
        "h1_daily_bias_continuation_sweep_edge.csv": pd.concat(h1_cont_rows, ignore_index=True) if h1_cont_rows else pd.DataFrame(),
    }

    for name, df in outputs.items():
        df.to_csv(OUT_DIR / name, index=False)

    input_meta = []
    for fp in drop_files:
        try:
            raw = app.load_dataframe(str(fp))
            cleaned, _ = app.prepare_tradingview_ohlc(raw)
            input_meta.append({
                "file": str(fp.relative_to(BASE_DIR)),
                "rows": int(len(cleaned)),
                "date_start_utc": cleaned["time"].min().isoformat() if len(cleaned) else None,
                "date_end_utc": cleaned["time"].max().isoformat() if len(cleaned) else None,
            })
        except Exception as exc:
            input_meta.append({"file": str(fp.relative_to(BASE_DIR)), "error": str(exc)})

    metadata = {
        "precomputed_at_utc": datetime.now(timezone.utc).isoformat(),
        "script": "scripts/precompute_stats.py",
        "git_commit": _git_commit(),
        "input_files": input_meta,
        "warnings": warnings,
        "failures": failures,
    }
    (OUT_DIR / "precompute_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
