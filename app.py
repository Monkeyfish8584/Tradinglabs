from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
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




def prepare_ohlc(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    out, _dropped = prepare_tradingview_ohlc(df)
    out = out.copy()
    out["time_london"] = out["time"].dt.tz_convert("Europe/London")
    out = out.sort_values("time_london").reset_index(drop=True)
    out["candle_start"] = out["time_london"]
    if timeframe == "1H":
        out["candle_end"] = out["candle_start"] + pd.Timedelta(hours=1)
    elif timeframe == "4H":
        out["candle_end"] = out["candle_start"] + pd.Timedelta(hours=4)
    elif timeframe == "1D":
        out["candle_end"] = out["candle_start"].shift(-1)
    else:
        raise ValueError(f"Unsupported timeframe for prepare_ohlc: {timeframe}")
    return out

def compute_daily_attack_stats(df_daily: pd.DataFrame) -> pd.DataFrame:
    df = prepare_ohlc(df_daily, "1D").copy()
    df["colour"] = "neutral"
    df.loc[df["close"] > df["open"], "colour"] = "green"
    df.loc[df["close"] < df["open"], "colour"] = "red"

    df["next_high"] = df["high"].shift(-1)
    df["next_low"] = df["low"].shift(-1)
    df["next_close"] = df["close"].shift(-1)

    green_cases = df[(df["colour"] == "green") & df["next_high"].notna()].copy()
    green_success = green_cases["next_high"] >= green_cases["high"]
    green_close_beyond = green_cases["next_close"] > green_cases["high"]

    red_cases = df[(df["colour"] == "red") & df["next_low"].notna()].copy()
    red_success = red_cases["next_low"] <= red_cases["low"]
    red_close_beyond = red_cases["next_close"] < red_cases["low"]

    return pd.DataFrame([
        {
            "Scenario": "Uses previous daily candle colour. Previous daily green → next day breaks previous high",
            "Total Cases": int(len(green_cases)),
            "Successful Attacks": int(green_success.sum()),
            "Attack %": pct(int(green_success.sum()), int(len(green_cases))),
            "Close Beyond Prev Level": int(green_close_beyond.sum()),
            "Close Beyond %": pct(int(green_close_beyond.sum()), int(len(green_cases))),
        },
        {
            "Scenario": "Uses previous daily candle colour. Previous daily red → next day breaks previous low",
            "Total Cases": int(len(red_cases)),
            "Successful Attacks": int(red_success.sum()),
            "Attack %": pct(int(red_success.sum()), int(len(red_cases))),
            "Close Beyond Prev Level": int(red_close_beyond.sum()),
            "Close Beyond %": pct(int(red_close_beyond.sum()), int(len(red_cases))),
        },
    ])


def compute_4h_attack_stats(
    df_daily: pd.DataFrame, df_4h: pd.DataFrame, instrument: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    overlap_label = "Core-session overlap 4H candle"
    next_label = "Next 4H candle"
    either_label = "Overlap OR next 4H candle"

    daily = prepare_ohlc(df_daily, "1D").copy()
    daily["daily_start"] = daily["time_london"]
    daily["daily_end"] = daily["candle_end"]
    daily = daily.dropna(subset=["daily_end"]).copy()
    daily["previous_daily_open"] = daily["open"]
    daily["previous_daily_high"] = daily["high"]
    daily["previous_daily_low"] = daily["low"]
    daily["previous_daily_close"] = daily["close"]
    daily["previous_daily_colour"] = "neutral"
    daily.loc[daily["previous_daily_close"] > daily["previous_daily_open"], "previous_daily_colour"] = "green"
    daily.loc[daily["previous_daily_close"] < daily["previous_daily_open"], "previous_daily_colour"] = "red"

    h4 = prepare_ohlc(df_4h, "4H").copy()
    h4["h4_start"] = h4["time_london"]
    h4["h4_end"] = h4["candle_end"]
    h4["h4_open"], h4["h4_high"], h4["h4_low"], h4["h4_close"] = h4["open"], h4["high"], h4["low"], h4["close"]

    def get_us_cash_open_london(trade_date: pd.Timestamp) -> pd.Timestamp:
        ny_open = pd.Timestamp(
            year=trade_date.year,
            month=trade_date.month,
            day=trade_date.day,
            hour=9,
            minute=30,
            tz="America/New_York",
        )
        return ny_open.tz_convert("Europe/London")

    if instrument in {"US30", "US500"}:
        h4["candle_start_london"] = h4["h4_start"]
        h4["candle_end_london"] = h4["h4_start"] + pd.Timedelta(hours=4)
        h4["calculated_us_cash_open_london"] = h4["h4_start"].dt.normalize().apply(get_us_cash_open_london)
        h4["overlaps_session"] = (h4["candle_start_london"] <= h4["calculated_us_cash_open_london"]) & (
            h4["candle_end_london"] > h4["calculated_us_cash_open_london"]
        )
        h4["selected_us_open_candle"] = h4["overlaps_session"]
        h4["session_start"] = h4["calculated_us_cash_open_london"]
        h4["session_end"] = h4["calculated_us_cash_open_london"]
    else:
        sstart, send = ("08:00", "10:00")
        session_start_td = pd.Timedelta(hours=int(sstart.split(":")[0]), minutes=int(sstart.split(":")[1]))
        session_end_td = pd.Timedelta(hours=int(send.split(":")[0]), minutes=int(send.split(":")[1]))
        h4["session_start"] = h4["h4_start"].dt.normalize() + session_start_td
        h4["session_end"] = h4["h4_start"].dt.normalize() + session_end_td
        h4["overlaps_session"] = (h4["h4_start"] < h4["session_end"]) & (h4["h4_end"] > h4["session_start"])
        h4["candle_start_london"] = h4["h4_start"]
        h4["candle_end_london"] = h4["h4_end"]
        h4["calculated_us_cash_open_london"] = pd.NaT
        h4["selected_us_open_candle"] = False
    h4["trade_day"] = h4["h4_start"].dt.date
    h4 = h4.reset_index(drop=True)
    h4["h4_seq"] = h4.index

    overlap = h4[h4["overlaps_session"]].groupby("trade_day", as_index=False).head(1).copy()
    overlap["4H Candle Group"] = overlap_label
    overlap["source_overlap_idx"] = overlap["h4_seq"]

    next_h4 = overlap[["source_overlap_idx"]].copy()
    next_h4["h4_seq"] = next_h4["source_overlap_idx"] + 1
    next_h4 = next_h4.merge(h4, on="h4_seq", how="left").dropna(subset=["h4_start"]).copy()
    next_h4["4H Candle Group"] = next_label

    selected = pd.concat([overlap, next_h4], ignore_index=True).sort_values("h4_start").reset_index(drop=True)
    if selected.empty:
        rows=[]
        for g in [overlap_label,next_label,either_label]:
            for sc in [
                "Uses previous daily candle colour. After green prev completed daily candle → attacks prev completed daily high",
                "Uses previous daily candle colour. After red prev completed daily candle → attacks prev completed daily low",
            ]:
                rows.append({"4H Candle Group":g,"Scenario":sc,"Total Cases":0,"Successful Attacks":0,"Attack %":0.0})
        return pd.DataFrame(rows), pd.DataFrame()

    selected["h4_start_merge"] = selected["h4_start"].dt.tz_localize(None)
    dmerge = daily[["daily_start","daily_end","previous_daily_open","previous_daily_high","previous_daily_low","previous_daily_close","previous_daily_colour"]].copy()
    dmerge["daily_end_merge"] = dmerge["daily_end"].dt.tz_localize(None)
    selected["h4_start_merge"] = pd.to_datetime(
        selected["h4_start_merge"],
        errors="coerce"
    ).astype("datetime64[ns]")
    dmerge["daily_end_merge"] = pd.to_datetime(
        dmerge["daily_end_merge"],
        errors="coerce"
    ).astype("datetime64[ns]")
    selected = selected.dropna(subset=["h4_start_merge"]).copy()
    dmerge = dmerge.dropna(subset=["daily_end_merge"]).copy()
    selected = selected.sort_values("h4_start_merge").reset_index(drop=True)
    dmerge = dmerge.sort_values("daily_end_merge").reset_index(drop=True)
    if selected["h4_start_merge"].dtype != dmerge["daily_end_merge"].dtype:
        raise ValueError(
            f"Merge key dtype mismatch: "
            f"h4_start_merge={selected['h4_start_merge'].dtype}, "
            f"daily_end_merge={dmerge['daily_end_merge'].dtype}"
        )
    # Match each 4H candle to the most recent daily candle that is already completed
    # at 4H open (daily_end <= h4_start). Example: Monday intraday 4H maps to Friday daily
    # until Monday daily has completed.
    selected = pd.merge_asof(
        selected,
        dmerge,
        left_on="h4_start_merge",
        right_on="daily_end_merge",
        direction="backward",
        allow_exact_matches=True,
        suffixes=("", "_daily"),
    )
    selected = selected.dropna(subset=["daily_start","daily_end"]).copy()
    selected = selected[selected["previous_daily_colour"].isin(["green","red"])].copy()

    selected["target_level"] = np.where(selected["previous_daily_colour"].eq("green"), selected["previous_daily_high"], selected["previous_daily_low"])
    selected["attack_success"] = np.where(selected["previous_daily_colour"].eq("green"), selected["h4_high"] >= selected["previous_daily_high"], selected["h4_low"] <= selected["previous_daily_low"])

    def stats_for(frame, label, color, scenario):
        s=frame[(frame["4H Candle Group"]==label)&(frame["previous_daily_colour"]==color)]
        return {"4H Candle Group":label,"Scenario":scenario,"Total Cases":int(len(s)),"Successful Attacks":int(s["attack_success"].sum()),"Attack %":pct(int(s["attack_success"].sum()),int(len(s)))}

    rows=[]
    rows.append(stats_for(selected, overlap_label, "green", "Uses previous daily candle colour. After green prev completed daily candle → attacks prev completed daily high"))
    rows.append(stats_for(selected, overlap_label, "red", "Uses previous daily candle colour. After red prev completed daily candle → attacks prev completed daily low"))
    rows.append(stats_for(selected, next_label, "green", "Uses previous daily candle colour. After green prev completed daily candle → attacks prev completed daily high"))
    rows.append(stats_for(selected, next_label, "red", "Uses previous daily candle colour. After red prev completed daily candle → attacks prev completed daily low"))

    ov=selected[selected["4H Candle Group"].eq(overlap_label)].copy()
    nx=selected[selected["4H Candle Group"].eq(next_label)][["source_overlap_idx","attack_success"]].copy().rename(columns={"attack_success":"next_attack_success"})
    paired=ov.merge(nx,on="source_overlap_idx",how="left")
    paired["either_success"]=paired["attack_success"]|paired["next_attack_success"].fillna(False)
    for color,scenario in [("green","Uses previous daily candle colour. After green prev completed daily candle → attacks prev completed daily high"),("red","Uses previous daily candle colour. After red prev completed daily candle → attacks prev completed daily low")]:
        s=paired[paired["previous_daily_colour"]==color]
        rows.append({"4H Candle Group":either_label,"Scenario":scenario,"Total Cases":int(len(s)),"Successful Attacks":int(s["either_success"].sum()),"Attack %":pct(int(s["either_success"].sum()),int(len(s)))})

    debug = selected[["4H Candle Group","h4_start","h4_end","session_start","session_end","overlaps_session","candle_start_london","candle_end_london","calculated_us_cash_open_london","selected_us_open_candle","h4_open","h4_high","h4_low","h4_close","daily_start","daily_end","previous_daily_open","previous_daily_high","previous_daily_low","previous_daily_close","previous_daily_colour","target_level","attack_success"]].copy()
    debug.insert(0,"asset",instrument)
    debug = debug.rename(columns={"daily_start":"matched previous daily start","daily_end":"matched previous daily end"})
    debug["warn_prev_daily_after_4h_start"] = debug["matched previous daily end"] > debug["h4_start"]
    debug["warn_same_containing_daily"] = (debug["matched previous daily start"] <= debug["h4_start"]) & (debug["matched previous daily end"] > debug["h4_start"])
    ratio = (debug["h4_high"] / debug["previous_daily_high"]).replace([np.inf, -np.inf], np.nan).abs()
    debug["warn_price_scale_mismatch"] = ~ratio.between(0.25, 4.0)
    return pd.DataFrame(rows), debug.sort_values("h4_start")


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


def add_scenario_column(table: pd.DataFrame, timeframe: str, instrument: str | None = None) -> pd.DataFrame:
    out = table.copy()
    if "Setup" not in out.columns:
        return out
    if timeframe == "1H":
        high_txt = "No daily bias used. Current 1H candle trades above previous 1H high and closes back below it."
        low_txt = "No daily bias used. Current 1H candle trades below previous 1H low and closes back above it."
    else:
        high_txt = "No daily bias used. Current 4H candle trades above previous 4H high and closes back below it."
        low_txt = "No daily bias used. Current 4H candle trades below previous 4H low and closes back above it."
    if instrument in {"GER40", "UK100", "US30", "US500"}:
        label = "GER40 / DAX" if instrument == "GER40" else instrument
        high_txt = f"No daily bias used. {label} core-session candle sweeps the previous candle high and closes back below it."
        low_txt = f"No daily bias used. {label} core-session candle sweeps the previous candle low and closes back above it."
    out.insert(out.columns.get_loc("Setup") + 1, "Scenario", out["Setup"].map({"High sweep": high_txt, "Low sweep": low_txt}).fillna(""))
    return out


def compute_us_session_4h_sweep_edge(df_4h: pd.DataFrame, instrument: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    if instrument not in {"US500", "US30"}:
        return pd.DataFrame(), pd.DataFrame(), {}

    selected_hour = 14 if instrument == "US500" else 15
    tested_label = "14:00–18:00 Europe/London 4H candle" if instrument == "US500" else "15:00–19:00 Europe/London 4H candle"
    compared_label = "Immediately previous 4H candle"

    h4 = prepare_ohlc(df_4h, "4H").copy().sort_values("time_london").reset_index(drop=True)
    h4["candle_start_london"] = h4["time_london"]
    h4["candle_end_london"] = h4["candle_start_london"] + pd.Timedelta(hours=4)
    h4["selected_session_candle"] = h4["candle_start_london"].dt.hour.eq(selected_hour)
    h4["previous_candle_start_london"] = h4["candle_start_london"].shift(1)
    h4["previous_candle_end_london"] = h4["candle_end_london"].shift(1)
    h4["previous_high"] = h4["high"].shift(1)
    h4["previous_low"] = h4["low"].shift(1)
    h4["selected_high"] = h4["high"]
    h4["selected_low"] = h4["low"]
    h4["selected_close"] = h4["close"]

    selected = h4[h4["selected_session_candle"]].dropna(subset=["previous_high", "previous_low"]).copy()
    selected["breaks_previous_high"] = selected["selected_high"] > selected["previous_high"]
    selected["breaks_previous_low"] = selected["selected_low"] < selected["previous_low"]
    selected["breaks_either_side"] = selected["breaks_previous_high"] | selected["breaks_previous_low"]
    selected["breaks_both_sides"] = selected["breaks_previous_high"] & selected["breaks_previous_low"]
    selected["high_break_fails"] = selected["breaks_previous_high"] & (selected["selected_close"] < selected["previous_high"])
    selected["low_break_fails"] = selected["breaks_previous_low"] & (selected["selected_close"] > selected["previous_low"])

    total_cases = int(len(selected))
    high_break_cases = int(selected["breaks_previous_high"].sum()) if total_cases else 0
    low_break_cases = int(selected["breaks_previous_low"].sum()) if total_cases else 0
    either_cases = int(selected["breaks_either_side"].sum()) if total_cases else 0
    both_cases = int(selected["breaks_both_sides"].sum()) if total_cases else 0
    high_break_fails = int(selected["high_break_fails"].sum()) if total_cases else 0
    low_break_fails = int(selected["low_break_fails"].sum()) if total_cases else 0

    result_table = pd.DataFrame(
        [{
            "Asset": instrument,
            "Setup": "High sweep / Low sweep",
            "Scenario": "No daily bias used. US500 14:00–18:00 4H candle is compared with the previous 10:00–14:00 4H candle." if instrument == "US500" else "No daily bias used. US30 15:00–19:00 4H candle is compared with the previous 11:00–15:00 4H candle.",
            "Candle Tested": tested_label,
            "Compared Against": compared_label,
            "Total Cases": total_cases,
            "Breaks Previous High Cases": high_break_cases,
            "Breaks Previous High %": pct(high_break_cases, total_cases),
            "Breaks Previous Low Cases": low_break_cases,
            "Breaks Previous Low %": pct(low_break_cases, total_cases),
            "Breaks Either Side Cases": either_cases,
            "Breaks Either Side %": pct(either_cases, total_cases),
            "Breaks Both Sides Cases": both_cases,
            "Breaks Both Sides %": pct(both_cases, total_cases),
            "High Break Fails Cases": high_break_fails,
            "High Break Fails %": pct(high_break_fails, high_break_cases),
            "Low Break Fails Cases": low_break_fails,
            "Low Break Fails %": pct(low_break_fails, low_break_cases),
        }]
    )

    debug = selected[
        [
            "time",
            "candle_start_london",
            "candle_end_london",
            "selected_session_candle",
            "previous_candle_start_london",
            "previous_candle_end_london",
            "previous_high",
            "previous_low",
            "selected_high",
            "selected_low",
            "selected_close",
            "breaks_previous_high",
            "breaks_previous_low",
            "breaks_either_side",
            "breaks_both_sides",
            "high_break_fails",
            "low_break_fails",
        ]
    ].copy()
    debug.insert(0, "asset", instrument)

    hour_counts = h4["candle_start_london"].dt.hour.value_counts().sort_index().to_dict()
    debug_counts = {"selected_hour": selected_hour, "total_h4_rows": int(len(h4)), "selected_rows": total_cases, "london_start_hour_counts": hour_counts}
    return result_table, debug, debug_counts


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

    st.markdown("### 3) Generic Sweep / Failed Breakout Stats")
    st.markdown("**1H Generic Sweep / Failed Breakout Stats — All Candles**")
    if h1_df is None:
        st.info("Not enough data loaded to calculate this sweep stat.")
    else:
        h1_table, h1_metrics = compute_sweep_stats(h1_df)
        h1_main = add_scenario_column(h1_table, "1H")[["Setup", "Scenario", "Total Cases", "Reversal-Colour %", "Failed-Sweep-Holds %"]]
        st.dataframe(h1_main.style.format({"Reversal-Colour %": "{:.2f}%", "Failed-Sweep-Holds %": "{:.2f}%"}), use_container_width=True)
        with st.expander("Full 1H generic sweep stats"):
            h1_full = add_scenario_column(h1_table, "1H")[["Setup", "Scenario", "Total Cases", "Reversal-Colour Cases", "Reversal-Colour %", "Failed-Sweep-Holds Cases", "Failed-Sweep-Holds %"]]
            st.dataframe(h1_full.style.format({"Reversal-Colour %": "{:.2f}%", "Failed-Sweep-Holds %": "{:.2f}%"}), use_container_width=True)
        st.caption("These stats are conditional on the scenario shown. Failed-sweep-holds % means the next candle did not reclaim the swept level. Daily-colour continuation stats require the previous completed daily candle to be green or red.")

    st.markdown("**4H Generic Sweep / Failed Breakout Stats — All Candles**")
    if h4_df is None:
        st.info("Not enough data loaded to calculate this sweep stat.")
    else:
        h4_table, h4_metrics = compute_sweep_stats(h4_df)
        h4_main = add_scenario_column(h4_table, "4H")[["Setup", "Scenario", "Total Cases", "Reversal-Colour %", "Failed-Sweep-Holds %"]]
        st.dataframe(h4_main.style.format({"Reversal-Colour %": "{:.2f}%", "Failed-Sweep-Holds %": "{:.2f}%"}), use_container_width=True)
        with st.expander("Full 4H generic sweep stats"):
            h4_full = add_scenario_column(h4_table, "4H")[["Setup", "Scenario", "Total Cases", "Reversal-Colour Cases", "Reversal-Colour %", "Failed-Sweep-Holds Cases", "Failed-Sweep-Holds %"]]
            st.dataframe(h4_full.style.format({"Reversal-Colour %": "{:.2f}%", "Failed-Sweep-Holds %": "{:.2f}%"}), use_container_width=True)
        st.caption("These stats are conditional on the scenario shown. Failed-sweep-holds % means the next candle did not reclaim the swept level. Daily-colour continuation stats require the previous completed daily candle to be green or red.")

    st.markdown("### 4) Core Session Sweep Stats")
    core_rows, debug_frames = [], []
    for tf, key in [("1H", h1_key), ("4H", h4_key)]:
        df = parsed.get(key)
        if df is None:
            continue
        mask = core_session_mask(df, instrument, tf)
        core_df = df[mask].copy()
        table, _metrics = compute_sweep_stats(core_df) if len(core_df) else (pd.DataFrame(), {})
        for _, r in table.iterrows():
            scenario = add_scenario_column(pd.DataFrame([r]), tf, instrument).iloc[0]["Scenario"]
            core_rows.append({"Timeframe": tf, "Setup": r["Setup"], "Scenario": scenario, "Total Cases": int(r["Total Cases"]), "Reversal-Colour Cases": int(r["Reversal-Colour Cases"]), "Reversal-Colour %": r["Reversal-Colour %"], "Failed-Sweep-Holds Cases": int(r["Failed-Sweep-Holds Cases"]), "Failed-Sweep-Holds %": r["Failed-Sweep-Holds %"], "Session Used": session_used})
        dbg = core_df[["time", "open", "high", "low", "close"]].copy()
        dbg["time_london"] = core_df["time"].dt.tz_convert("Europe/London")
        dbg["timeframe"] = tf
        debug_frames.append(dbg)
    if core_rows:
        core_table = pd.DataFrame(core_rows)
        core_summary = core_table[["Timeframe", "Setup", "Scenario", "Total Cases", "Reversal-Colour %", "Failed-Sweep-Holds %", "Session Used"]]
        st.dataframe(core_summary.style.format({"Reversal-Colour %": "{:.2f}%", "Failed-Sweep-Holds %": "{:.2f}%"}), use_container_width=True)
        with st.expander("Full core-session sweep stats"):
            st.dataframe(core_table.style.format({"Reversal-Colour %": "{:.2f}%", "Failed-Sweep-Holds %": "{:.2f}%"}), use_container_width=True)
    else:
        st.info("Not enough data loaded to calculate this sweep stat.")

    with st.expander("Core-session sweep debug"):
        if debug_frames:
            st.dataframe(pd.concat(debug_frames, ignore_index=True), use_container_width=True)
        else:
            st.info("No core-session rows available.")
    with st.expander("Generic sweep debug"):
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

def render_us_session_4h_sweep_edge(parsed: dict[str, pd.DataFrame], instrument: str) -> None:
    if instrument not in {"US500", "US30"}:
        st.info("US Session 4H Sweep Edge applies only to US30 and US500.")
        return
    st.markdown("### 5) US Session 4H Sweep Edge")
    h4_key = f"{instrument}_4H"
    h4_df = parsed.get(h4_key)
    if h4_df is None:
        st.info("Not enough matching 4H candles found for this asset/session.")
        return

    table, debug, debug_counts = compute_us_session_4h_sweep_edge(h4_df, instrument)
    if table.empty or int(table.iloc[0]["Total Cases"]) == 0:
        st.info("Not enough matching 4H candles found for this asset/session.")
        st.write(debug_counts)
        return

    st.dataframe(
        table.style.format({
            "Breaks Previous High %": "{:.2f}%",
            "Breaks Previous Low %": "{:.2f}%",
            "Breaks Either Side %": "{:.2f}%",
            "Breaks Both Sides %": "{:.2f}%",
            "High Break Fails %": "{:.2f}%",
            "Low Break Fails %": "{:.2f}%",
        }),
        use_container_width=True,
    )
    with st.expander("US Session 4H Sweep Debug"):
        st.dataframe(debug.head(50), use_container_width=True)
        st.write(debug_counts)


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


def compute_1h_daily_bias_continuation_sweep_edge(parsed: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    config = {
        "GER40": {"label": "GER40 / DAX", "session": "UK Open / Morning", "hours": [8, 9, 10, 11], "window_end_exclusive": 12},
        "UK100": {"label": "UK100", "session": "UK Open / Morning", "hours": [8, 9, 10, 11], "window_end_exclusive": 12},
        "US500": {"label": "US500", "session": "US Session", "hours": [14, 15, 16, 17], "window_end_exclusive": 18},
        "US30": {"label": "US30", "session": "US Session", "hours": [15, 16, 17, 18], "window_end_exclusive": 19},
    }
    cont_rows: list[dict] = []
    debug_rows: list[pd.DataFrame] = []

    for asset, cfg in config.items():
        h1_key, d1_key = f"{asset}_1H", f"{asset}_1D"
        if h1_key not in parsed or d1_key not in parsed:
            continue

        h1 = prepare_ohlc(parsed[h1_key], "1H").copy().sort_values("time_london").reset_index(drop=True)
        h1["hour"] = h1["time_london"].dt.hour
        h1["prev_1h_start_london"] = h1["time_london"].shift(1)
        h1["previous_1h_high"] = h1["high"].shift(1)
        h1["previous_1h_low"] = h1["low"].shift(1)

        d1 = prepare_ohlc(parsed[d1_key], "1D").copy().sort_values("time_london").reset_index(drop=True)
        d1["daily_start"] = d1["time_london"]
        d1["daily_end"] = d1["candle_end"]
        d1 = d1.dropna(subset=["daily_end"]).copy()
        d1["previous_daily_colour"] = "neutral"
        d1.loc[d1["close"] > d1["open"], "previous_daily_colour"] = "green"
        d1.loc[d1["close"] < d1["open"], "previous_daily_colour"] = "red"

        h1["h1_start_merge"] = h1["time_london"].dt.tz_localize(None).astype("datetime64[ns]")
        d1["daily_end_merge"] = d1["daily_end"].dt.tz_localize(None).astype("datetime64[ns]")

        merged = pd.merge_asof(
            h1.sort_values("h1_start_merge"),
            d1[["daily_start", "daily_end", "daily_end_merge", "previous_daily_colour"]].sort_values("daily_end_merge"),
            left_on="h1_start_merge",
            right_on="daily_end_merge",
            direction="backward",
        ).sort_values("time_london").reset_index(drop=True)

        tested = merged[merged["hour"].isin(cfg["hours"])].copy()

        tested["bullish_setup_triggered"] = (
            (tested["previous_daily_colour"] == "green")
            & (tested["low"] < tested["previous_1h_low"])
            & (tested["close"] > tested["previous_1h_low"])
        )
        tested["bearish_setup_triggered"] = (
            (tested["previous_daily_colour"] == "red")
            & (tested["high"] > tested["previous_1h_high"])
            & (tested["close"] < tested["previous_1h_high"])
        )

        tested["later_window_high"] = np.nan
        tested["later_window_low"] = np.nan
        tested["bullish_success"] = pd.NA
        tested["bearish_success"] = pd.NA

        for idx in tested.index:
            row = tested.loc[idx]
            later = tested[
                (tested["time_london"].dt.date == row["time_london"].date())
                & (tested["hour"] > row["hour"])
                & (tested["hour"] < cfg["window_end_exclusive"])
            ]
            if later.empty:
                continue
            tested.loc[idx, "later_window_high"] = later["high"].max()
            tested.loc[idx, "later_window_low"] = later["low"].min()
            if row["bullish_setup_triggered"]:
                tested.loc[idx, "bullish_success"] = bool((later["high"] > row["previous_1h_high"]).any())
            if row["bearish_setup_triggered"]:
                tested.loc[idx, "bearish_success"] = bool((later["low"] < row["previous_1h_low"]).any())

        for hour in cfg["hours"]:
            subset = tested[tested["hour"] == hour]
            for setup, col, succ in [
                ("Bullish", "bullish_setup_triggered", "bullish_success"),
                ("Bearish", "bearish_setup_triggered", "bearish_success"),
            ]:
                set_rows = subset[subset[col]]
                total_cases = int(len(set_rows))
                valid = set_rows[succ].isin([True, False])
                valid_cases = int(valid.sum())
                success_cases = int(set_rows[succ].eq(True).sum())
                success_pct = np.nan if valid_cases == 0 else pct(success_cases, valid_cases)
                scenario = (
                    "Uses previous daily candle colour. Previous daily candle was green; selected 1H candle sweeps previous 1H low and closes back above it; later session/window breaks upward through the opposite previous 1H high."
                    if setup == "Bullish"
                    else "Uses previous daily candle colour. Previous daily candle was red; selected 1H candle sweeps previous 1H high and closes back below it; later session/window breaks downward through the opposite previous 1H low."
                )
                cont_rows.append(
                    {
                        "Asset": cfg["label"],
                        "Session": cfg["session"],
                        "Hour": f"{hour:02d}:00",
                        "Setup": setup,
                        "Scenario": scenario,
                        "Total Cases": total_cases,
                        "Successful Continuation Cases": success_cases,
                        "Success %": success_pct,
                    }
                )

        dbg = tested[["time_london", "hour", "prev_1h_start_london", "previous_1h_high", "previous_1h_low", "open", "high", "low", "close", "daily_start", "daily_end", "previous_daily_colour", "bullish_setup_triggered", "bearish_setup_triggered", "later_window_high", "later_window_low", "bullish_success", "bearish_success"]].copy()
        dbg.insert(0, "asset", asset)
        dbg = dbg.rename(columns={"time_london": "candle_start_london", "open": "current_open", "high": "current_high", "low": "current_low", "close": "current_close", "daily_start": "previous_daily_start", "daily_end": "previous_daily_end"})
        debug_rows.append(dbg)

    return pd.DataFrame(cont_rows), (pd.concat(debug_rows, ignore_index=True) if debug_rows else pd.DataFrame())


def render_1h_daily_bias_continuation_sweep_edge(parsed: dict[str, pd.DataFrame]) -> None:
    st.markdown("### 6) 1H Daily-Bias Continuation Sweep Edge")
    st.caption("Uses previous daily candle colour.")
    cont, debug = compute_1h_daily_bias_continuation_sweep_edge(parsed)
    if cont.empty:
        st.info("1H Daily-Bias Continuation Sweep Edge requires 1H + 1D files for GER40, UK100, US30, and US500.")
        return
    table = cont[["Asset", "Session", "Hour", "Setup", "Scenario", "Total Cases", "Successful Continuation Cases", "Success %"]].copy()
    st.dataframe(table.sort_values(["Asset", "Hour", "Setup"]).style.format({"Success %": lambda v: "N/A" if pd.isna(v) else f"{v:.2f}%"}), use_container_width=True)
    with st.expander("1H daily-bias continuation sweep debug"):
        st.dataframe(debug.head(50), use_container_width=True)

def main() -> None:
    st.set_page_config(page_title="Trading Dashboard Data Hub", layout="wide")
    st.title("Trading Dashboard: Data Upload Hub")
    st.caption("Upload your trading files now so we can use them to power the dashboard.")

    st.subheader("1) GitHub dropzone files")
    with st.expander("GitHub dropzone files (click to expand)", expanded=False):
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

    st.subheader("2) Previous Day High/Low Attack")
    parsed, parse_warnings, parse_failures = parse_dropzone_market_files(drop_files)
    for warning_msg in parse_warnings:
        st.warning(warning_msg)
    for failure_msg in parse_failures:
        st.error(failure_msg)

    st.markdown("#### Dashboard Tabs")
    trading_tab, ger40_tab, uk100_tab, us30_tab, us500_tab = st.tabs(["Trading View", "GER40", "UK100", "US30", "US500"])

    with trading_tab:
        render_trading_view(parsed, drop_files)
        render_1h_daily_bias_continuation_sweep_edge(parsed)

    with ger40_tab:
        st.markdown("### 1) Daily Attack Stats")
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

        st.markdown("### 2) 4H Daily-Level Attack Stats")
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
        st.markdown("### 1) Daily Attack Stats")
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

        st.markdown("### 2) 4H Daily-Level Attack Stats")
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
        render_us_session_4h_sweep_edge(parsed, "US30")

    with us500_tab:
        st.markdown("### 1) Daily Attack Stats")
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

        st.markdown("### 2) 4H Daily-Level Attack Stats")
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
        render_us_session_4h_sweep_edge(parsed, "US500")

    with uk100_tab:
        st.markdown("### 1) Daily Attack Stats")
        if "UK100_1D" in parsed:
            uk100_daily = compute_daily_attack_stats(parsed["UK100_1D"])
            st.dataframe(
                uk100_daily.style.format({"Attack %": "{:.2f}%", "Close Beyond %": "{:.2f}%"}),
                use_container_width=True,
            )
            st.caption("UK100 uses London-session instrument handling (08:00–10:00 Europe/London).")
        else:
            st.info("UK100 daily stats skipped (file unavailable or parse failed).")

        st.markdown("### 2) 4H Daily-Level Attack Stats")
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
