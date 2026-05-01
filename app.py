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
    daily = df_daily.copy()
    daily["time_london"] = daily["time"].dt.tz_convert("Europe/London")
    daily["date_london"] = daily["time_london"].dt.date
    daily = daily.set_index("date_london")

    h4 = df_4h.copy()
    h4["time_london"] = h4["time"].dt.tz_convert("Europe/London")
    h4["time_new_york"] = h4["time"].dt.tz_convert("America/New_York")
    h4["candle_start_london"] = h4["time_london"]
    h4["candle_end_london"] = h4["candle_start_london"] + pd.Timedelta(hours=4)
    h4["candle_start_utc"] = h4["time"]
    h4["candle_end_utc"] = h4["time"] + pd.Timedelta(hours=4)
    h4["candle_start_new_york"] = h4["time_new_york"]
    h4["candle_end_new_york"] = h4["candle_start_new_york"] + pd.Timedelta(hours=4)
    h4["date_london"] = h4["time_london"].dt.date

    if instrument in {"GER40", "UK100"}:
        session_start = pd.to_datetime("08:00").time()
        session_end = pd.to_datetime("10:00").time()
        overlap_label = f"{instrument} London session overlap candle"
        next_label = f"Next {instrument} 4H candle"
    else:
        session_start = pd.to_datetime("14:30").time()
        session_end = pd.to_datetime("16:30").time()
        overlap_label = "US open overlap candle"
        next_label = "Next US30 4H candle"

    h4["session_start"] = h4["candle_start_london"].dt.normalize() + pd.to_timedelta(
        session_start.hour, unit="h"
    ) + pd.to_timedelta(session_start.minute, unit="m")
    h4["session_end"] = h4["candle_start_london"].dt.normalize() + pd.to_timedelta(
        session_end.hour, unit="h"
    ) + pd.to_timedelta(session_end.minute, unit="m")
    h4["overlaps_instrument_window"] = (h4["candle_start_london"] < h4["session_end"]) & (
        h4["candle_end_london"] > h4["session_start"]
    )
    ny_start = h4["candle_start_new_york"].dt.normalize() + pd.Timedelta(hours=9, minutes=30)
    ny_end = h4["candle_start_new_york"].dt.normalize() + pd.Timedelta(hours=11, minutes=30)
    h4["overlaps_ny_0930_1130"] = (h4["candle_start_new_york"] < ny_end) & (h4["candle_end_new_york"] > ny_start)
    h4["session_label"] = pd.NA
    h4.loc[h4["overlaps_instrument_window"], "session_label"] = overlap_label
    h4.loc[h4["overlaps_instrument_window"].shift(1, fill_value=False), "session_label"] = next_label

    merged = h4.copy()
    merged["prev_daily_date"] = merged["date_london"].apply(lambda d: d - pd.Timedelta(days=1))
    merged = merged[merged["prev_daily_date"].isin(daily.index)]
    merged["prev_open"] = merged["prev_daily_date"].map(daily["open"])
    merged["prev_close"] = merged["prev_daily_date"].map(daily["close"])
    merged["prev_high"] = merged["prev_daily_date"].map(daily["high"])
    merged["prev_low"] = merged["prev_daily_date"].map(daily["low"])
    merged["prev_color"] = pd.Series(pd.NA, index=merged.index, dtype="object")
    merged.loc[merged["prev_close"] > merged["prev_open"], "prev_color"] = "green"
    merged.loc[merged["prev_close"] < merged["prev_open"], "prev_color"] = "red"

    rows = []
    for label in [overlap_label, next_label]:
        sample_label = merged[merged["session_label"] == label]
        green_sample = sample_label[sample_label["prev_color"] == "green"]
        green_success = int((green_sample["high"] > green_sample["prev_high"]).sum())
        green_total = int(green_sample.shape[0])
        rows.append(
            {
                "4H Candle": label,
                "Scenario": "After green prev daily candle → attacks prev daily high",
                "Total Cases": green_total,
                "Successful Attacks": green_success,
                "Attack %": (green_success / green_total * 100.0) if green_total else 0.0,
            }
        )

        red_sample = sample_label[sample_label["prev_color"] == "red"]
        red_success = int((red_sample["low"] < red_sample["prev_low"]).sum())
        red_total = int(red_sample.shape[0])
        rows.append(
            {
                "4H Candle": label,
                "Scenario": "After red prev daily candle → attacks prev daily low",
                "Total Cases": red_total,
                "Successful Attacks": red_success,
                "Attack %": (red_success / red_total * 100.0) if red_total else 0.0,
            }
        )

    debug_cols = [
        "candle_start_utc",
        "candle_end_utc",
        "candle_start_london",
        "candle_end_london",
        "candle_start_new_york",
        "candle_end_new_york",
        "session_label",
        "overlaps_instrument_window",
        "overlaps_ny_0930_1130",
        "prev_daily_date",
        "prev_color",
        "prev_high",
        "prev_low",
    ]
    debug = merged[debug_cols].sort_values("candle_start_utc").copy()
    debug["detected_instrument"] = instrument
    return pd.DataFrame(rows), debug


def save_upload(uploaded_file) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = uploaded_file.name.replace("/", "_")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target_path = DATA_DIR / f"{timestamp}_{safe_name}"

    with target_path.open("wb") as out:
        out.write(uploaded_file.getbuffer())

    return build_metadata(target_path, source="streamlit_upload")


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

    st.markdown("#### Asset stats")
    ger40_tab, uk100_tab, us30_tab, us500_tab = st.tabs(["GER40", "UK100", "US30", "US500"])

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

            with st.expander("Debug details (for validation when numbers differ)"):
                st.markdown("**Session overlap diagnostics and daily matching details**")
                st.dataframe(debug, use_container_width=True)
                st.write(f"Number of matched 4H cases: {len(debug):,}")
        else:
            st.info("GER40 4H candle stats skipped (required GER40 daily/4H file unavailable or parse failed).")

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

            with st.expander("Debug details (for validation when numbers differ)"):
                st.markdown("**Session overlap diagnostics and daily matching details**")
                st.dataframe(debug, use_container_width=True)
                st.write(f"Number of matched 4H cases: {len(debug):,}")
        else:
            st.info("US30 4H candle stats skipped (required US30 daily/4H file unavailable or parse failed).")

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

            with st.expander("Debug details (for validation when numbers differ)"):
                st.markdown("**Session overlap diagnostics and daily matching details**")
                st.dataframe(debug, use_container_width=True)
                st.write(f"Number of matched 4H cases: {len(debug):,}")
        else:
            st.info("US500 4H candle stats skipped (required US500 daily/4H file unavailable or parse failed).")

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
            with st.expander("Debug details (for validation when numbers differ)"):
                st.markdown("**Session overlap diagnostics and daily matching details**")
                st.dataframe(debug, use_container_width=True)
                st.write(f"Number of matched 4H cases: {len(debug):,}")
        else:
            st.info("UK100 4H candle stats skipped (required UK100 daily/4H file unavailable or parse failed).")

        st.markdown("**1H file status (loaded + validated for future 08:00–10:00 precision analysis)**")
        if "UK100_1H" in parsed:
            st.success(f"UK100 1H file loaded and validated ({len(parsed['UK100_1H']):,} cleaned rows).")
        else:
            st.info("UK100 1H file validation skipped (file unavailable or parse failed).")


if __name__ == "__main__":
    main()
