from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "uploads"
CATALOG_PATH = BASE_DIR / "data" / "catalog.json"
GITHUB_DROPZONE = BASE_DIR / "github_data" / "dropzone"
SUPPORTED_INSTRUMENTS = {"GER40", "US30", "US500", "UK100"}
TIMEFRAME_TO_SUFFIX = {"1D": "1D", "4H": "4H", "1H": "1H"}


@st.cache_data
def load_dataframe(path: str) -> pd.DataFrame:
    file_path = Path(path)
    if file_path.suffix.lower() == ".csv":
        return pd.read_csv(file_path)
    if file_path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(file_path)
    raise ValueError(f"Unsupported file type: {file_path.suffix}")


def load_catalog() -> list[dict]:
    if not CATALOG_PATH.exists():
        return []
    with CATALOG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_catalog(entries: list[dict]) -> None:
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CATALOG_PATH.open("w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


def list_github_dropzone_files() -> list[Path]:
    if not GITHUB_DROPZONE.exists():
        return []
    files = [
        p
        for p in GITHUB_DROPZONE.iterdir()
        if p.is_file() and p.suffix.lower() in {".csv", ".parquet", ".pq"}
    ]
    return sorted(files)


def build_metadata(file_path: Path, source: str) -> dict:
    df = load_dataframe(str(file_path))
    return {
        "file_name": file_path.name,
        "saved_path": str(file_path),
        "uploaded_at_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "source": source,
        "rows": int(df.shape[0]),
        "columns": int(df.shape[1]),
        "column_names": list(df.columns),
    }


def detect_instrument(file_name: str) -> str:
    upper_name = file_name.upper()
    if "UK100" in upper_name:
        return "UK100"
    if "GER40" in upper_name:
        return "GER40"
    if "US500" in upper_name:
        return "US500"
    if "US30" in upper_name:
        return "US30"
    return "UNKNOWN"


def detect_timeframe(file_name: str) -> str:
    upper_name = file_name.upper()
    if "1D" in upper_name:
        return "1D"
    if "240" in upper_name:
        return "4H"
    if "60" in upper_name:
        return "1H"
    return "UNKNOWN"


def file_profile(file_path: Path) -> dict:
    instrument = detect_instrument(file_path.name)
    timeframe = detect_timeframe(file_path.name)
    date_range = "n/a"
    rows = 0
    try:
        cleaned, _ = prepare_tradingview_ohlc(load_dataframe(str(file_path)))
        rows = int(cleaned.shape[0])
        if rows:
            date_range = (
                f"{cleaned['time'].min().strftime('%Y-%m-%d %H:%M:%S %Z')} → "
                f"{cleaned['time'].max().strftime('%Y-%m-%d %H:%M:%S %Z')}"
            )
    except Exception:
        pass
    return {
        "file_name": file_path.name,
        "instrument": instrument,
        "timeframe": timeframe,
        "rows": rows,
        "date_range": date_range,
    }


def parse_dropzone_market_files(drop_files: list[Path]) -> tuple[dict[str, pd.DataFrame], list[str], list[str]]:
    parsed: dict[str, pd.DataFrame] = {}
    warnings: list[str] = []
    failures: list[str] = []

    for file_path in drop_files:
        instrument = detect_instrument(file_path.name)
        timeframe = detect_timeframe(file_path.name)
        if instrument not in SUPPORTED_INSTRUMENTS or timeframe not in TIMEFRAME_TO_SUFFIX:
            continue
        parsed_key = f"{instrument}_{TIMEFRAME_TO_SUFFIX[timeframe]}"
        try:
            cleaned, dropped = prepare_tradingview_ohlc(load_dataframe(str(file_path)))
            parsed[parsed_key] = cleaned
            if dropped:
                warnings.append(f"{file_path.name}: dropped {dropped} row(s) due to invalid/duplicate OHLC data.")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{file_path.name}: failed to parse ({exc})")
    return parsed, warnings, failures


def sync_dropzone_to_catalog() -> tuple[int, int]:
    catalog = load_catalog()
    known_paths = {item.get("saved_path") for item in catalog}
    imported = 0
    skipped = 0

    for file_path in list_github_dropzone_files():
        if str(file_path) in known_paths:
            skipped += 1
            continue
        catalog.append(build_metadata(file_path, source="github_dropzone"))
        imported += 1

    if imported:
        save_catalog(catalog)
    return imported, skipped


def ensure_dropzone_catalog_synced() -> tuple[int, int]:
    """Always keep catalog aligned with committed github_data/dropzone files."""
    return sync_dropzone_to_catalog()


def prepare_tradingview_ohlc(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    required = ["time", "open", "high", "low", "close"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    out = df[required].copy()
    out = out[out["time"].astype(str).str.lower() != "time"].copy()
    if pd.api.types.is_numeric_dtype(out["time"]):
        out["time"] = pd.to_datetime(out["time"], unit="s", utc=True, errors="coerce")
    else:
        out["time"] = pd.to_datetime(out["time"], utc=True, errors="coerce", format="mixed")
    for col in ["open", "high", "low", "close"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    before = len(out)
    out = out.dropna(subset=required).sort_values("time").reset_index(drop=True)
    dropped = before - len(out)
    return out, dropped


def compute_daily_attack_stats(df_daily: pd.DataFrame) -> pd.DataFrame:
    df = df_daily.copy()
    df["prev_open"] = df["open"].shift(1)
    df["prev_close"] = df["close"].shift(1)
    df["prev_high"] = df["high"].shift(1)
    df["prev_low"] = df["low"].shift(1)
    df["prev_date"] = df["time"].shift(1).dt.date
    df = df.dropna(subset=["prev_open", "prev_close", "prev_high", "prev_low"]).copy()

    prev_green = df["prev_close"] > df["prev_open"]
    prev_red = df["prev_close"] < df["prev_open"]

    green_total = int(prev_green.sum())
    green_break = int((prev_green & (df["high"] > df["prev_high"])).sum())
    green_close_beyond = int((prev_green & (df["close"] > df["prev_high"])).sum())

    red_total = int(prev_red.sum())
    red_break = int((prev_red & (df["low"] < df["prev_low"])).sum())
    red_close_beyond = int((prev_red & (df["close"] < df["prev_low"])).sum())

    def pct(num: int, den: int) -> float:
        return (num / den * 100.0) if den else 0.0

    return pd.DataFrame(
        [
            {
                "Scenario": "Prev daily green → next day breaks prev high",
                "Total Cases": green_total,
                "Successful Attacks": green_break,
                "Attack %": pct(green_break, green_total),
                "Close Beyond Prev Level": green_close_beyond,
                "Close Beyond %": pct(green_close_beyond, green_total),
            },
            {
                "Scenario": "Prev daily red → next day breaks prev low",
                "Total Cases": red_total,
                "Successful Attacks": red_break,
                "Attack %": pct(red_break, red_total),
                "Close Beyond Prev Level": red_close_beyond,
                "Close Beyond %": pct(red_close_beyond, red_total),
            },
        ]
    )


def compute_4h_attack_stats(
    df_daily: pd.DataFrame, df_4h: pd.DataFrame, instrument: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily = df_daily.copy().sort_values("time").reset_index(drop=True)
    daily["time_london"] = daily["time"].dt.tz_convert("Europe/London")
    daily["daily_start"] = daily["time_london"]
    daily["daily_end"] = daily["daily_start"].shift(-1)
    daily = daily.dropna(subset=["daily_end"]).copy()

    h4 = df_4h.copy().sort_values("time").reset_index(drop=True)
    h4["time_london"] = h4["time"].dt.tz_convert("Europe/London")
    h4["candle_start_london"] = h4["time_london"]
    h4["candle_end_london"] = h4["candle_start_london"] + pd.Timedelta(hours=4)

    if instrument in {"GER40", "UK100"}:
        session_start = pd.to_datetime("08:00").time()
        session_end = pd.to_datetime("10:00").time()
    else:
        session_start = pd.to_datetime("14:30").time()
        session_end = pd.to_datetime("16:30").time()
    overlap_label = "Core-session overlap 4H candle"
    next_label = "Next 4H candle"
    either_label = "Overlap OR next 4H candle"

    h4["session_start"] = h4["candle_start_london"].dt.normalize() + pd.to_timedelta(
        session_start.hour, unit="h"
    ) + pd.to_timedelta(session_start.minute, unit="m")
    h4["session_end"] = h4["candle_start_london"].dt.normalize() + pd.to_timedelta(
        session_end.hour, unit="h"
    ) + pd.to_timedelta(session_end.minute, unit="m")
    h4["overlaps_instrument_window"] = (h4["candle_start_london"] < h4["session_end"]) & (
        h4["candle_end_london"] > h4["session_start"]
    )
    h4["trade_date_london"] = h4["candle_start_london"].dt.date
    overlap = h4[h4["overlaps_instrument_window"]].groupby("trade_date_london", as_index=False).head(1).copy()
    overlap["4H Candle Group"] = overlap_label
    next_c = h4.loc[overlap.index + 1].copy()
    next_c["4H Candle Group"] = next_label
    next_c["source_overlap_idx"] = overlap.index.to_numpy()

    selected = pd.concat([overlap, next_c], ignore_index=True).sort_values("candle_start_london").reset_index(drop=True)
    daily_match = daily[["daily_start", "daily_end", "time_london", "open", "high", "low", "close"]].sort_values("daily_end")
    selected = pd.merge_asof(
        selected.sort_values("candle_start_london"),
        daily_match,
        left_on="candle_start_london",
        right_on="daily_end",
        direction="backward",
        allow_exact_matches=True,
    )
    selected = selected.dropna(subset=["daily_start", "daily_end"]).copy()
    selected = selected.rename(columns={"time_london_y": "matched_daily_timestamp", "open_y": "previous_daily_open", "high_y": "previous_daily_high", "low_y": "previous_daily_low", "close_y": "previous_daily_close"})
    selected["previous_daily_colour"] = pd.Series(pd.NA, index=selected.index, dtype="object")
    selected.loc[selected["previous_daily_close"] > selected["previous_daily_open"], "previous_daily_colour"] = "green"
    selected.loc[selected["previous_daily_close"] < selected["previous_daily_open"], "previous_daily_colour"] = "red"
    selected = selected[selected["previous_daily_colour"].isin(["green", "red"])].copy()
    selected["target_level"] = np.where(selected["previous_daily_colour"].eq("green"), selected["previous_daily_high"], selected["previous_daily_low"])
    selected["attack_success"] = np.where(
        selected["previous_daily_colour"].eq("green"),
        selected["high"] >= selected["previous_daily_high"],
        selected["low"] <= selected["previous_daily_low"],
    )

    rows = []
    for label in [overlap_label, next_label]:
        for color, scenario in [
            ("green", "After green prev completed daily candle → attacks prev completed daily high"),
            ("red", "After red prev completed daily candle → attacks prev completed daily low"),
        ]:
            s = selected[(selected["4H Candle Group"] == label) & (selected["previous_daily_colour"] == color)]
            rows.append({"4H Candle Group": label, "Scenario": scenario, "Total Cases": int(len(s)), "Successful Attacks": int(s["attack_success"].sum()), "Attack %": pct(int(s["attack_success"].sum()), int(len(s)))})

    overlap_rows = selected[selected["4H Candle Group"].eq(overlap_label)].copy()
    next_rows = selected[selected["4H Candle Group"].eq(next_label)].copy()
    paired = overlap_rows.merge(next_rows[["source_overlap_idx", "attack_success"]], left_on=overlap_rows.index, right_on="source_overlap_idx", how="left", suffixes=("", "_next"))
    paired["either_success"] = paired["attack_success"] | paired["attack_success_next"].fillna(False)
    for color, scenario in [("green", "After green prev completed daily candle → attacks prev completed daily high"), ("red", "After red prev completed daily candle → attacks prev completed daily low")]:
        s = paired[paired["previous_daily_colour"] == color]
        rows.append({"4H Candle Group": either_label, "Scenario": scenario, "Total Cases": int(len(s)), "Successful Attacks": int(s["either_success"].sum()), "Attack %": pct(int(s["either_success"].sum()), int(len(s)))})

    debug_cols = [
        "4H Candle Group",
        "time",
        "candle_start_london",
        "candle_end_london",
        "session_start",
        "session_end",
        "overlaps_instrument_window",
        "open",
        "high",
        "low",
        "close",
        "matched_daily_timestamp",
        "daily_start",
        "daily_end",
        "previous_daily_open",
        "previous_daily_high",
        "previous_daily_low",
        "previous_daily_close",
        "previous_daily_colour",
        "target_level",
        "attack_success",
    ]
    debug = selected[debug_cols].sort_values("candle_start_london").copy()
    debug["asset"] = instrument
    debug["warn_prev_daily_after_4h_start"] = debug["daily_end"] > debug["candle_start_london"]
    debug["warn_same_containing_daily"] = (debug["daily_start"] <= debug["candle_start_london"]) & (debug["daily_end"] > debug["candle_start_london"])
    price_ratio = (debug["high"] / debug["previous_daily_high"]).replace([np.inf, -np.inf], np.nan).abs()
    debug["warn_price_scale_mismatch"] = ~price_ratio.between(0.25, 4.0)
    return pd.DataFrame(rows), debug


def pct(num: int, den: int) -> float:
    return (num / den * 100.0) if den else 0.0


def compute_sweep_stats(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    work = df.copy().sort_values("time").reset_index(drop=True)
    work["prev_high"] = work["high"].shift(1)
    work["prev_low"] = work["low"].shift(1)
    work["next_open"] = work["open"].shift(-1)
    work["next_close"] = work["close"].shift(-1)
    work = work.dropna(subset=["prev_high", "prev_low", "next_open", "next_close"]).copy()

    high_sweep = (work["high"] > work["prev_high"]) & (work["close"] < work["prev_high"])
    low_sweep = (work["low"] < work["prev_low"]) & (work["close"] > work["prev_low"])
    high_next_red = high_sweep & (work["next_close"] < work["next_open"])
    low_next_green = low_sweep & (work["next_close"] > work["next_open"])
    high_holds = high_sweep & (work["next_close"] < work["prev_high"])
    low_holds = low_sweep & (work["next_close"] > work["prev_low"])

    metrics = {
        "high_total": int(high_sweep.sum()),
        "high_next_red": int(high_next_red.sum()),
        "high_holds": int(high_holds.sum()),
        "low_total": int(low_sweep.sum()),
        "low_next_green": int(low_next_green.sum()),
        "low_holds": int(low_holds.sum()),
    }
    table = pd.DataFrame(
        [
            {"Setup": "High sweep", "Total Cases": metrics["high_total"], "Reversal-Colour Cases": metrics["high_next_red"], "Reversal-Colour %": pct(metrics["high_next_red"], metrics["high_total"]), "Failed-Sweep-Holds Cases": metrics["high_holds"], "Failed-Sweep-Holds %": pct(metrics["high_holds"], metrics["high_total"])},
            {"Setup": "Low sweep", "Total Cases": metrics["low_total"], "Reversal-Colour Cases": metrics["low_next_green"], "Reversal-Colour %": pct(metrics["low_next_green"], metrics["low_total"]), "Failed-Sweep-Holds Cases": metrics["low_holds"], "Failed-Sweep-Holds %": pct(metrics["low_holds"], metrics["low_total"])},
        ]
    )
    return table, metrics


def core_session_mask(df: pd.DataFrame, instrument: str, timeframe: str) -> pd.Series:
    london = df["time"].dt.tz_convert("Europe/London")
    if instrument in {"GER40", "UK100"}:
        if timeframe == "1H":
            return london.dt.hour.isin([8, 9])
        session_start_time, session_end_time = pd.to_datetime("08:00").time(), pd.to_datetime("10:00").time()
    else:
        if timeframe == "1H":
            return london.dt.hour.isin([14, 15, 16])
        session_start_time, session_end_time = pd.to_datetime("14:30").time(), pd.to_datetime("16:30").time()
    candle_start = london
    candle_end = london + pd.Timedelta(hours=4)
    session_start = candle_start.dt.normalize() + pd.to_timedelta(session_start_time.hour, unit="h") + pd.to_timedelta(session_start_time.minute, unit="m")
    session_end = candle_start.dt.normalize() + pd.to_timedelta(session_end_time.hour, unit="h") + pd.to_timedelta(session_end_time.minute, unit="m")
    return (candle_start < session_end) & (candle_end > session_start)


def render_sweep_sections(parsed: dict[str, pd.DataFrame], instrument: str) -> None:
    h1_key, h4_key = f"{instrument}_1H", f"{instrument}_4H"
    h1_df, h4_df = parsed.get(h1_key), parsed.get(h4_key)
    session_used = "08:00–10:00 Europe/London" if instrument in {"GER40", "UK100"} else "14:30–16:30 Europe/London"

    st.markdown("**1H Sweep / Failed Breakout Stats**")
    if h1_df is None:
        st.info("Not enough data loaded to calculate this sweep stat.")
    else:
        h1_table, h1_metrics = compute_sweep_stats(h1_df)
        st.dataframe(h1_table.style.format({"Reversal-Colour %": "{:.2f}%", "Failed-Sweep-Holds %": "{:.2f}%"}), use_container_width=True)
        with st.expander("Full 1H sweep stats"):
            st.dataframe(h1_table.style.format({"Reversal-Colour %": "{:.2f}%", "Failed-Sweep-Holds %": "{:.2f}%"}), use_container_width=True)

    st.markdown("**4H Sweep / Failed Breakout Stats**")
    if h4_df is None:
        st.info("Not enough data loaded to calculate this sweep stat.")
    else:
        h4_table, h4_metrics = compute_sweep_stats(h4_df)
        st.dataframe(h4_table.style.format({"Reversal-Colour %": "{:.2f}%", "Failed-Sweep-Holds %": "{:.2f}%"}), use_container_width=True)
        with st.expander("Full 4H sweep stats"):
            st.dataframe(h4_table.style.format({"Reversal-Colour %": "{:.2f}%", "Failed-Sweep-Holds %": "{:.2f}%"}), use_container_width=True)

    st.markdown("**Core Session Sweep Stats**")
    core_rows, debug_frames = [], []
    for tf, key in [("1H", h1_key), ("4H", h4_key)]:
        df = parsed.get(key)
        if df is None:
            continue
        mask = core_session_mask(df, instrument, tf)
        core_df = df[mask].copy()
        table, _metrics = compute_sweep_stats(core_df) if len(core_df) else (pd.DataFrame(), {})
        for _, r in table.iterrows():
            core_rows.append({"Timeframe": tf, "Setup": r["Setup"], "Total Cases": int(r["Total Cases"]), "Reversal-Colour Cases": int(r["Reversal-Colour Cases"]), "Reversal-Colour %": r["Reversal-Colour %"], "Failed-Sweep-Holds Cases": int(r["Failed-Sweep-Holds Cases"]), "Failed-Sweep-Holds %": r["Failed-Sweep-Holds %"], "Session Used": session_used})
        dbg = core_df[["time", "open", "high", "low", "close"]].copy()
        dbg["time_london"] = core_df["time"].dt.tz_convert("Europe/London")
        dbg["timeframe"] = tf
        debug_frames.append(dbg)
    if core_rows:
        core_table = pd.DataFrame(core_rows)
        st.dataframe(core_table.style.format({"Reversal-Colour %": "{:.2f}%", "Failed-Sweep-Holds %": "{:.2f}%"}), use_container_width=True)
    else:
        st.info("Not enough data loaded to calculate this sweep stat.")

    st.markdown("**High Probability Sweep Summary**")
    summary = []
    label_map = {
        ("1H", "High sweep", "Failed-Sweep-Holds %"): "1H high sweep → next candle stays below swept high",
        ("1H", "Low sweep", "Failed-Sweep-Holds %"): "1H low sweep → next candle stays above swept low",
        ("4H", "High sweep", "Failed-Sweep-Holds %"): "4H high sweep → next candle stays below swept high",
        ("4H", "Low sweep", "Failed-Sweep-Holds %"): "4H low sweep → next candle stays above swept low",
    }
    if core_rows:
        all_rows = []
        if h1_df is not None:
            all_rows += [{"Timeframe": "1H", **r} for r in compute_sweep_stats(h1_df)[0].to_dict("records")]
        if h4_df is not None:
            all_rows += [{"Timeframe": "4H", **r} for r in compute_sweep_stats(h4_df)[0].to_dict("records")]
        for row in all_rows:
            hold_pct = row["Failed-Sweep-Holds %"]
            rev_pct = row["Reversal-Colour %"]
            if hold_pct >= 60:
                edge = "Strong edge" if hold_pct >= 70 else "Useful edge"
                txt = label_map[(row["Timeframe"], row["Setup"], "Failed-Sweep-Holds %")]
                summary.append({"Timeframe": row["Timeframe"], "Signal": txt, "Metric": "Failed-Sweep-Holds %", "Value": hold_pct, "Edge": edge, "Interpretation": "After price sweeps the previous candle high and closes back inside, the next candle often fails to reclaim that swept high." if row["Setup"] == "High sweep" else "After price sweeps the previous candle low and closes back inside, the next candle often holds above that swept low."})
            if rev_pct >= 60:
                edge = "Strong edge" if rev_pct >= 70 else "Useful edge"
                summary.append({"Timeframe": row["Timeframe"], "Signal": f"{row['Timeframe']} {row['Setup'].lower()} → next candle reversal-colour", "Metric": "Reversal-Colour % (weaker)", "Value": rev_pct, "Edge": edge, "Interpretation": "This measures next-candle colour only, so treat it as weaker than the failed-level hold stat."})
    if summary:
        st.dataframe(pd.DataFrame(summary).sort_values(["Timeframe", "Metric"]), use_container_width=True)
    else:
        st.info("No high-probability sweep stats (>= 60%) found for this asset.")

    with st.expander("Core-session sweep debug"):
        if debug_frames:
            st.dataframe(pd.concat(debug_frames, ignore_index=True), use_container_width=True)
        else:
            st.info("No core-session rows available.")
    with st.expander("Data validation details"):
        rows = []
        for tf, key in [("1H", h1_key), ("4H", h4_key)]:
            df = parsed.get(key)
            if df is None:
                rows.append({"timeframe": tf, "file_used": "missing", "rows": 0, "date_range": "n/a", "total_sweep_cases": 0, "core_session_sweep_cases": 0})
                continue
            totals = compute_sweep_stats(df)[1]
            core_totals = compute_sweep_stats(df[core_session_mask(df, instrument, tf)])[1] if len(df) else {"high_total": 0, "low_total": 0}
            rows.append({"timeframe": tf, "file_used": key, "rows": len(df), "date_range": f"{df['time'].min()} -> {df['time'].max()}", "total_sweep_cases": totals["high_total"] + totals["low_total"], "core_session_sweep_cases": core_totals["high_total"] + core_totals["low_total"]})
        st.write({"asset_selected": instrument, "timezone_conversion_used": "UTC -> Europe/London"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True)


def save_upload(uploaded_file) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = uploaded_file.name.replace("/", "_")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target_path = DATA_DIR / f"{timestamp}_{safe_name}"

    with target_path.open("wb") as out:
        out.write(uploaded_file.getbuffer())

    return build_metadata(target_path, source="streamlit_upload")



def session_window_for_instrument(instrument: str) -> str:
    return "08:00–10:00 Europe/London" if instrument in {"GER40", "UK100"} else "14:30–16:30 Europe/London"


def pick_daily_row(stats: pd.DataFrame, prev_color: str) -> pd.Series:
    if prev_color == "Green":
        return stats.iloc[0]
    return stats.iloc[1]


def pick_4h_rows(stats: pd.DataFrame, instrument: str, prev_color: str) -> pd.DataFrame:
    overlap_label = "Core-session overlap 4H candle"
    next_label = "Next 4H candle"
    either_label = "Overlap OR next 4H candle"
    scenario = (
        "After green prev completed daily candle → attacks prev completed daily high"
        if prev_color == "Green"
        else "After red prev completed daily candle → attacks prev completed daily low"
    )
    return stats[(stats["4H Candle Group"].isin([overlap_label, next_label, either_label])) & (stats["Scenario"] == scenario)].copy()


def render_trading_view(parsed: dict[str, pd.DataFrame], drop_files: list[Path]) -> None:
    st.subheader("Pre-Trade Trading View")
    asset = st.selectbox("Asset", ["GER40", "UK100", "US30", "US500"], index=0)
    prev_color = st.radio("Previous completed daily candle colour", ["Green", "Red"], horizontal=True)
    threshold = st.slider("Probability threshold", min_value=50, max_value=90, value=60, step=1) / 100

    window = session_window_for_instrument(asset)
    target = "Previous Daily High" if prev_color == "Green" else "Previous Daily Low"
    focus = "upper-liquidity / bullish" if prev_color == "Green" else "lower-liquidity / bearish"

    st.markdown("### Today’s Context")
    st.info(
        f"{asset} after a {prev_color.lower()} daily close. Focus area: {target.lower()} during the {window} window. "
        f"This is a historical bias/stat tool only ({focus} attack context)."
    )

    daily_key = f"{asset}_1D"
    h4_key = f"{asset}_4H"
    h1_key = f"{asset}_1H"

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### Core Session Attack Stat")
        if daily_key in parsed and h4_key in parsed:
            h4_stats, _ = compute_4h_attack_stats(parsed[daily_key], parsed[h4_key], instrument=asset)
            rows = pick_4h_rows(h4_stats, asset, prev_color)
            overlap_row = rows.iloc[0] if len(rows) else None
            if overlap_row is not None:
                cases = int(overlap_row["Total Cases"])
                success = int(overlap_row["Successful Attacks"])
                atk = float(overlap_row["Attack %"]) / 100
                st.metric("Cases", cases)
                st.metric("Successful attacks", success)
                st.metric("Attack %", f"{atk*100:.2f}%")
                st.metric("Meets threshold", "Yes" if atk >= threshold else "No")
                st.caption(
                    f"Historically, when the previous {asset} daily candle closed {prev_color.lower()}, "
                    f"the {window} session attacked the {target.lower()} {atk*100:.2f}% of the time."
                )
            else:
                st.info("Core-session 4H context data not loaded yet.")
        else:
            st.info("Core-session 4H context data not loaded yet.")

    with c2:
        st.markdown("### Full-Day Attack Stat")
        if daily_key in parsed:
            d = compute_daily_attack_stats(parsed[daily_key])
            row = pick_daily_row(d, prev_color)
            cases = int(row["Total Cases"])
            success = int(row["Successful Attacks"])
            atk = float(row["Attack %"]) / 100
            st.metric("Cases", cases)
            st.metric("Successful attacks", success)
            st.metric("Attack %", f"{atk*100:.2f}%")
            st.caption("Historically, this condition has led to the selected daily liquidity target attack at the rate shown above.")
        else:
            st.info("Daily data not loaded yet.")

    st.markdown("### 4H Context")
    if daily_key in parsed and h4_key in parsed:
        h4_stats, _ = compute_4h_attack_stats(parsed[daily_key], parsed[h4_key], instrument=asset)
        rows = pick_4h_rows(h4_stats, asset, prev_color)
        if len(rows):
            st.dataframe(rows[["4H Candle Group", "Total Cases", "Successful Attacks", "Attack %"]].style.format({"Attack %": "{:.2f}%"}), use_container_width=True)
        else:
            st.info("4H context data not loaded yet.")
    else:
        st.info("4H context data not loaded yet.")

    st.markdown("### High Probability Setups")
    hp_rows = []
    if daily_key in parsed:
        d = compute_daily_attack_stats(parsed[daily_key])
        r = pick_daily_row(d, prev_color)
        if float(r["Attack %"]) / 100 >= threshold:
            hp_rows.append({"Setup": "Full-Day Attack", "Cases": int(r["Total Cases"]), "Attack %": float(r["Attack %"])})
    if daily_key in parsed and h4_key in parsed:
        h4_stats, _ = compute_4h_attack_stats(parsed[daily_key], parsed[h4_key], instrument=asset)
        rows = pick_4h_rows(h4_stats, asset, prev_color)
        for _, rr in rows.iterrows():
            if float(rr["Attack %"]) / 100 >= threshold:
                hp_rows.append({"Setup": rr["4H Candle Group"], "Cases": int(rr["Total Cases"]), "Attack %": float(rr["Attack %"])})
    if hp_rows:
        st.dataframe(pd.DataFrame(hp_rows).style.format({"Attack %": "{:.2f}%"}), use_container_width=True)
    else:
        st.info("No high-probability historical setup found for this condition.")

    st.markdown("### Caution Notes")
    notes = ["This dashboard does not have live data and cannot determine whether a level has already been attacked today.",
             "This view is a historical bias/stat tool, not a trade signal."]
    missing = [tf for tf,key in [("1D",daily_key),("4H",h4_key),("1H",h1_key)] if key not in parsed]
    if missing:
        notes.append(f"Missing data warning: {', '.join(missing)} file(s) unavailable for {asset}.")
    # low sample warnings
    if daily_key in parsed:
        d = compute_daily_attack_stats(parsed[daily_key])
        if int(pick_daily_row(d, prev_color)["Total Cases"]) < 30:
            notes.append("Low sample size warning: fewer than 30 daily cases for this condition.")
    if daily_key in parsed and h4_key in parsed:
        h4_stats,_ = compute_4h_attack_stats(parsed[daily_key], parsed[h4_key], instrument=asset)
        rows = pick_4h_rows(h4_stats, asset, prev_color)
        if len(rows) and rows["Total Cases"].min() < 30:
            notes.append("Low sample size warning: fewer than 30 cases in at least one 4H context setup.")
    providers = set()
    for f in drop_files:
        if asset not in f.name.upper():
            continue
        parts = f.stem.split('_')
        providers.add(parts[0].lower())
    if len(providers) > 1:
        notes.append("Mixed broker/feed warning: this asset appears to use multiple file/provider naming sources across loaded timeframes.")
    for n in notes:
        st.warning(n)

def main() -> None:
    st.set_page_config(page_title="Trading Dashboard Data Hub", layout="wide")
    st.title("Trading Dashboard: Data Upload Hub")
    st.caption("Upload your trading files now so we can use them to power the dashboard.")

    st.subheader("1) Upload data")
    uploaded_file = st.file_uploader(
        "Supported file types: CSV, Parquet",
        type=["csv", "parquet", "pq"],
        accept_multiple_files=False,
    )

    if uploaded_file is not None:
        try:
            metadata = save_upload(uploaded_file)
            catalog = load_catalog()
            catalog.append(metadata)
            save_catalog(catalog)
            st.success(f"Saved {metadata['file_name']} with {metadata['rows']} rows.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Upload failed: {exc}")

    st.subheader("2) GitHub dropzone files")
    st.caption("Committed files in github_data/dropzone are auto-loaded into the catalog.")
    imported, skipped = ensure_dropzone_catalog_synced()
    drop_files = list_github_dropzone_files()
    if drop_files:
        dropzone_table = pd.DataFrame([file_profile(f) for f in drop_files])
        st.dataframe(
            dropzone_table[["file_name", "instrument", "timeframe", "rows", "date_range"]],
            use_container_width=True,
        )
        if imported:
            st.success(f"Auto-sync complete: imported {imported}, skipped {skipped} existing file(s).")
    else:
        st.info("No files found in github_data/dropzone yet.")

    st.subheader("3) Previous Day High/Low Attack")
    parsed, parse_warnings, parse_failures = parse_dropzone_market_files(drop_files)
    for warning_msg in parse_warnings:
        st.warning(warning_msg)
    for failure_msg in parse_failures:
        st.error(failure_msg)

    st.markdown("#### Dashboard Tabs")
    trading_tab, ger40_tab, uk100_tab, us30_tab, us500_tab = st.tabs(["Trading View", "GER40", "UK100", "US30", "US500"])

    with trading_tab:
        render_trading_view(parsed, drop_files)

    with ger40_tab:
        st.markdown("**Daily attack stats**")
        if "GER40_1D" in parsed:
            ger40_daily = compute_daily_attack_stats(parsed["GER40_1D"])
            st.dataframe(
                ger40_daily.style.format({"Attack %": "{:.2f}%", "Close Beyond %": "{:.2f}%"}),
                use_container_width=True,
            )
            st.caption(
                "GER40: green-candle follow-through is shown by high breaks, red-candle follow-through by low breaks; "
                "close-beyond columns show stronger continuation confirmation."
            )
        else:
            st.info("GER40 daily stats skipped (file unavailable or parse failed).")

        st.markdown("**4H candle attack stats (session-specific candles)**")
        if "GER40_1D" in parsed and "GER40_4H" in parsed:
            h4_stats, debug = compute_4h_attack_stats(parsed["GER40_1D"], parsed["GER40_4H"], instrument="GER40")
            st.dataframe(h4_stats.style.format({"Attack %": "{:.2f}%"}), use_container_width=True)
            st.caption(
                "GER40 labels only the candle overlapping 08:00–10:00 Europe/London plus the immediate next 4H candle."
            )

            with st.expander("4H attack matching debug"):
                st.dataframe(debug.head(200), use_container_width=True)
                st.write(f"Number of matched 4H cases: {len(debug):,}")
                if debug["warn_prev_daily_after_4h_start"].any():
                    st.warning("Validation warning: matched previous daily end is after 4H candle start for some rows.")
                if debug["warn_same_containing_daily"].any():
                    st.warning("Validation warning: matched daily appears to be containing day instead of previous completed day for some rows.")
                if debug["warn_price_scale_mismatch"].any():
                    st.warning("Validation warning: possible 4H/daily price scale mismatch detected in sample.")
                if len(debug) < 30:
                    st.warning("Validation warning: total 4H matched cases are unexpectedly low.")
        else:
            st.info("GER40 4H candle stats skipped (required GER40 daily/4H file unavailable or parse failed).")
        render_sweep_sections(parsed, "GER40")

    with us30_tab:
        st.markdown("**Daily attack stats**")
        if "US30_1D" in parsed:
            us30_daily = compute_daily_attack_stats(parsed["US30_1D"])
            st.dataframe(
                us30_daily.style.format({"Attack %": "{:.2f}%", "Close Beyond %": "{:.2f}%"}),
                use_container_width=True,
            )
            st.caption(
                "US30: green-candle follow-through is shown by high breaks, red-candle follow-through by low breaks; "
                "close-beyond columns show stronger continuation confirmation."
            )
        else:
            st.info("US30 daily stats skipped (file unavailable or parse failed).")

        st.markdown("**4H candle attack stats (session-specific candles)**")
        if "US30_1D" in parsed and "US30_4H" in parsed:
            h4_stats, debug = compute_4h_attack_stats(parsed["US30_1D"], parsed["US30_4H"], instrument="US30")
            st.dataframe(h4_stats.style.format({"Attack %": "{:.2f}%"}), use_container_width=True)
            st.caption(
                "US30 labels only the candle overlapping 14:30–16:30 Europe/London plus the immediate next 4H candle."
            )

            with st.expander("4H attack matching debug"):
                st.dataframe(debug.head(200), use_container_width=True)
                st.write(f"Number of matched 4H cases: {len(debug):,}")
                if debug["warn_prev_daily_after_4h_start"].any():
                    st.warning("Validation warning: matched previous daily end is after 4H candle start for some rows.")
                if debug["warn_same_containing_daily"].any():
                    st.warning("Validation warning: matched daily appears to be containing day instead of previous completed day for some rows.")
                if debug["warn_price_scale_mismatch"].any():
                    st.warning("Validation warning: possible 4H/daily price scale mismatch detected in sample.")
                if len(debug) < 30:
                    st.warning("Validation warning: total 4H matched cases are unexpectedly low.")
        else:
            st.info("US30 4H candle stats skipped (required US30 daily/4H file unavailable or parse failed).")
        render_sweep_sections(parsed, "US30")

    with us500_tab:
        st.markdown("**Daily attack stats**")
        if "US500_1D" in parsed:
            us500_daily = compute_daily_attack_stats(parsed["US500_1D"])
            st.dataframe(
                us500_daily.style.format({"Attack %": "{:.2f}%", "Close Beyond %": "{:.2f}%"}),
                use_container_width=True,
            )
            st.caption(
                "US500: green-candle follow-through is shown by high breaks, red-candle follow-through by low breaks; "
                "close-beyond columns show stronger continuation confirmation."
            )
        else:
            st.info("US500 daily stats skipped (file unavailable or parse failed).")

        st.markdown("**4H candle attack stats (session-specific candles)**")
        if "US500_1D" in parsed and "US500_4H" in parsed:
            h4_stats, debug = compute_4h_attack_stats(parsed["US500_1D"], parsed["US500_4H"], instrument="US500")
            st.dataframe(h4_stats.style.format({"Attack %": "{:.2f}%"}), use_container_width=True)
            st.caption(
                "US500 labels only the candle overlapping 14:30–16:30 Europe/London plus the immediate next 4H candle."
            )

            with st.expander("4H attack matching debug"):
                st.dataframe(debug.head(200), use_container_width=True)
                st.write(f"Number of matched 4H cases: {len(debug):,}")
                if debug["warn_prev_daily_after_4h_start"].any():
                    st.warning("Validation warning: matched previous daily end is after 4H candle start for some rows.")
                if debug["warn_same_containing_daily"].any():
                    st.warning("Validation warning: matched daily appears to be containing day instead of previous completed day for some rows.")
                if debug["warn_price_scale_mismatch"].any():
                    st.warning("Validation warning: possible 4H/daily price scale mismatch detected in sample.")
                if len(debug) < 30:
                    st.warning("Validation warning: total 4H matched cases are unexpectedly low.")
        else:
            st.info("US500 4H candle stats skipped (required US500 daily/4H file unavailable or parse failed).")
        render_sweep_sections(parsed, "US500")

    with uk100_tab:
        st.markdown("**Daily attack stats**")
        if "UK100_1D" in parsed:
            uk100_daily = compute_daily_attack_stats(parsed["UK100_1D"])
            st.dataframe(
                uk100_daily.style.format({"Attack %": "{:.2f}%", "Close Beyond %": "{:.2f}%"}),
                use_container_width=True,
            )
            st.caption("UK100 uses London-session instrument handling (08:00–10:00 Europe/London).")
        else:
            st.info("UK100 daily stats skipped (file unavailable or parse failed).")

        st.markdown("**4H candle attack stats (session-specific candles)**")
        if "UK100_1D" in parsed and "UK100_4H" in parsed:
            h4_stats, debug = compute_4h_attack_stats(parsed["UK100_1D"], parsed["UK100_4H"], instrument="UK100")
            st.dataframe(h4_stats.style.format({"Attack %": "{:.2f}%"}), use_container_width=True)
            st.caption(
                "UK100 labels only the candle overlapping 08:00–10:00 Europe/London plus the immediate next 4H candle."
            )
            with st.expander("4H attack matching debug"):
                st.dataframe(debug.head(200), use_container_width=True)
                st.write(f"Number of matched 4H cases: {len(debug):,}")
                if debug["warn_prev_daily_after_4h_start"].any():
                    st.warning("Validation warning: matched previous daily end is after 4H candle start for some rows.")
                if debug["warn_same_containing_daily"].any():
                    st.warning("Validation warning: matched daily appears to be containing day instead of previous completed day for some rows.")
                if debug["warn_price_scale_mismatch"].any():
                    st.warning("Validation warning: possible 4H/daily price scale mismatch detected in sample.")
                if len(debug) < 30:
                    st.warning("Validation warning: total 4H matched cases are unexpectedly low.")
        else:
            st.info("UK100 4H candle stats skipped (required UK100 daily/4H file unavailable or parse failed).")
        render_sweep_sections(parsed, "UK100")

        st.markdown("**1H file status (loaded + validated for future 08:00–10:00 precision analysis)**")
        if "UK100_1H" in parsed:
            st.success(f"UK100 1H file loaded and validated ({len(parsed['UK100_1H']):,} cleaned rows).")
        else:
            st.info("UK100 1H file validation skipped (file unavailable or parse failed).")


if __name__ == "__main__":
    main()
