# Trading Dashboard Data Hub

This project starts with a simple upload app so you can store trading datasets and use them to power your dashboard.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## What it does

- Upload CSV or Parquet files.
- Saves files under `data/uploads/` with UTC timestamped filenames.
- Tracks metadata in `data/catalog.json`.
- Lets you preview uploaded data and chart a numeric column.

## Next steps

- Add schema mapping for OHLCV fields.
- Connect indicators and strategy backtests.
- Add authentication and cloud storage.

## GitHub upload area (for now)

If you want a simple GitHub area to save files immediately, use `github_data/dropzone/`.

- Put CSV/Parquet files there.
- Commit and push to GitHub.
- In the app, click **Sync dropzone files into catalog** to register them for preview/charting.

