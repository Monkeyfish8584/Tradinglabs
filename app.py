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
TARGET_FILES = {
    "VANTAGE_GER40, 1D.csv": "GER40_1D",
    "VANTAGE_GER40, 240.csv": "GER40_4H",
    "BLACKBULL_US30, 1D.csv": "US30_1D",
    "BLACKBULL_US30, 240.csv": "US30_4H",
}


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
    try:
        out["time"] = pd.to_datetime(out["time"], utc=True, errors="coerce", format="mixed")
    except TypeError:
        out["time"] = pd.to_datetime(out["time"], utc=True, errors="coerce")
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


def compute_ger40_morning_stats(df_daily: pd.DataFrame, df_4h: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    daily = df_daily.copy()
    daily["date"] = daily["time"].dt.date
    daily = daily.set_index("date")

    h4 = df_4h.copy()
    h4["date"] = h4["time"].dt.date
    h4["clock"] = h4["time"].dt.strftime("%H:%M")
    starts = (
        h4["clock"]
        .value_counts()
        .rename_axis("4H Start Time")
        .reset_index(name="Count")
        .sort_values("4H Start Time")
    )

    morning = h4[h4["clock"].isin(["05:15", "09:15"])].copy()
    morning["prev_daily_date"] = morning["date"].apply(lambda d: d - pd.Timedelta(days=1))
    morning = morning[morning["prev_daily_date"].isin(daily.index)]
    morning["prev_open"] = morning["prev_daily_date"].map(daily["open"])
    morning["prev_close"] = morning["prev_daily_date"].map(daily["close"])
    morning["prev_high"] = morning["prev_daily_date"].map(daily["high"])
    morning["prev_low"] = morning["prev_daily_date"].map(daily["low"])
    morning["prev_color"] = pd.Series(pd.NA, index=morning.index, dtype="object")
    morning.loc[morning["prev_close"] > morning["prev_open"], "prev_color"] = "green"
    morning.loc[morning["prev_close"] < morning["prev_open"], "prev_color"] = "red"

    def summarize(candle_time: str, color: str, side: str) -> tuple[int, int]:
        sample = morning[(morning["clock"] == candle_time) & (morning["prev_color"] == color)]
        if side == "high":
            success = (sample["high"] > sample["prev_high"]).sum()
        else:
            success = (sample["low"] < sample["prev_low"]).sum()
        return int(sample.shape[0]), int(success)

    rows = []
    for color, side, label in [
        ("green", "high", "breaks prev daily high"),
        ("red", "low", "breaks prev daily low"),
    ]:
        for ctime, cname in [("05:15", "First morning"), ("09:15", "Second morning")]:
            total, success = summarize(ctime, color, side)
            rows.append(
                {
                    "Scenario": f"{cname} ({ctime}) after {color} prev daily candle → {label}",
                    "Total Cases": total,
                    "Successful Attacks": success,
                    "Attack %": (success / total * 100.0) if total else 0.0,
                }
            )

    debug_cols = ["time", "clock", "date", "prev_daily_date", "prev_color", "prev_high", "prev_low"]
    return pd.DataFrame(rows), starts, morning[debug_cols].sort_values("time")


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
        dropzone_table = pd.DataFrame([build_metadata(f, source="github_dropzone") for f in drop_files])
        st.dataframe(dropzone_table[["file_name", "rows", "columns"]], use_container_width=True)
        if imported:
            st.success(f"Auto-sync complete: imported {imported}, skipped {skipped} existing file(s).")
    else:
        st.info("No files found in github_data/dropzone yet.")

    st.subheader("3) Previous Day High/Low Attack")
    focus_files = [GITHUB_DROPZONE / name for name in TARGET_FILES]
    missing_focus = [p.name for p in focus_files if not p.exists()]
    if missing_focus:
        st.error(f"Missing required committed CSV(s): {missing_focus}")
        return

    parsed: dict[str, pd.DataFrame] = {}
    failed_files: list[str] = []
    for name, key in TARGET_FILES.items():
        try:
            cleaned, dropped = prepare_tradingview_ohlc(load_dataframe(str(GITHUB_DROPZONE / name)))
            parsed[key] = cleaned
            if dropped:
                st.warning(f"{name}: dropped {dropped} row(s) due to invalid/duplicate OHLC data.")
        except Exception as exc:  # noqa: BLE001
            failed_files.append(name)
            st.error(f"{name}: failed to parse ({exc})")

    st.markdown("#### Asset stats")
    ger40_tab, us30_tab = st.tabs(["GER40", "US30"])

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

        st.markdown("**4H second-morning-candle stats**")
        if "GER40_1D" in parsed and "GER40_4H" in parsed:
            h4_stats, starts, debug = compute_ger40_morning_stats(parsed["GER40_1D"], parsed["GER40_4H"])
            st.dataframe(h4_stats.style.format({"Attack %": "{:.2f}%"}), use_container_width=True)
            st.caption(
                "Comparison of first (≈05:15) vs second (≈09:15) morning 4H candles, conditioned on previous daily candle color."
            )

            with st.expander("Debug details (for validation when numbers differ)"):
                st.markdown("**Detected 4H candle start times**")
                st.dataframe(starts, use_container_width=True)
                st.markdown("**Daily/4H matching sample (includes matched daily date and previous daily candle date)**")
                st.dataframe(debug, use_container_width=True)
                st.write(f"Number of matched morning cases: {len(debug):,}")
        else:
            st.info("GER40 4H morning stats skipped (required GER40 daily/4H file unavailable or parse failed).")

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

    st.subheader("4) Uploaded datasets")
    catalog = load_catalog()
    if not catalog:
        st.info("No datasets uploaded yet.")
        return

    table = pd.DataFrame(catalog)
    st.dataframe(table, use_container_width=True)

    selected_path = st.selectbox("Choose dataset to preview", table["saved_path"].tolist())
    df = load_dataframe(selected_path)

    st.subheader("5) Dataset preview")
    st.write(f"Rows: {len(df):,} | Columns: {len(df.columns):,}")
    st.dataframe(df.head(200), use_container_width=True)

    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if numeric_cols:
        st.subheader("6) Quick numeric chart")
        y_col = st.selectbox("Numeric column", numeric_cols)
        st.line_chart(df[y_col])


if __name__ == "__main__":
    main()
