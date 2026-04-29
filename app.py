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
    files = [p for p in GITHUB_DROPZONE.iterdir() if p.is_file() and p.suffix.lower() in {".csv", ".parquet", ".pq"}]
    return sorted(files)


def save_upload(uploaded_file) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = uploaded_file.name.replace("/", "_")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target_path = DATA_DIR / f"{timestamp}_{safe_name}"

    with target_path.open("wb") as out:
        out.write(uploaded_file.getbuffer())

    df = load_dataframe(str(target_path))
    metadata = {
        "file_name": uploaded_file.name,
        "saved_path": str(target_path),
        "uploaded_at_utc": timestamp,
        "rows": int(df.shape[0]),
        "columns": int(df.shape[1]),
        "column_names": list(df.columns),
    }
    return metadata


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
    st.caption("You can commit files into github_data/dropzone/ and they appear here.")
    drop_files = list_github_dropzone_files()
    if drop_files:
        st.write([f.name for f in drop_files])
    else:
        st.info("No files found in github_data/dropzone yet.")

    st.subheader("3) Uploaded datasets")
    catalog = load_catalog()
    if not catalog:
        st.info("No datasets uploaded yet.")
        return

    table = pd.DataFrame(catalog)
    st.dataframe(table, use_container_width=True)

    selected_path = st.selectbox("Choose dataset to preview", table["saved_path"].tolist())
    df = load_dataframe(selected_path)

    st.subheader("4) Dataset preview")
    st.write(f"Rows: {len(df):,} | Columns: {len(df.columns):,}")
    st.dataframe(df.head(200), use_container_width=True)

    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if numeric_cols:
        st.subheader("5) Quick numeric chart")
        y_col = st.selectbox("Numeric column", numeric_cols)
        st.line_chart(df[y_col])


if __name__ == "__main__":
    main()
