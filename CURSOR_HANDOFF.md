# Continue Tradinglabs in Cursor

Clone this repository and open `Tradinglabs.code-workspace` in Cursor. Both applications are available in one workspace and use their own runtime and dependencies.

## Trading statistics app

The Streamlit app lives at the repository root. Its Python entry point is `app.py`. The folders `github_data/dropzone/` and `data/precomputed/` hold the trading datasets and calculated statistics. Run it from the repository root with `python -m streamlit run app.py`. The default local address is `http://localhost:8501`.

## Stock research desk

The stock dashboard lives in `research-desk/`. Its `START-HERE.md` contains the verified local build and database initialization commands. Run those commands from `research-desk/`. The app uses React, TypeScript, Vinext and a local Cloudflare D1 database. The production build runs locally through Wrangler. For hot reload, use `pnpm dev` after initializing the database. Open the URL printed by the command.

The local copy starts with six dated public sample snapshots. The hosted dashboard has its own database containing the live watchlist, notes and manual corrections. A deployment or data migration needs its own explicit configuration. The exported `.openai/hosting.json` supplies the DB binding for local development.

The workspace’s Terminal > Run Task menu includes install and run commands for both apps. Complete the database setup in `research-desk/START-HERE.md` before running the research desk for the first time.

## Research code map and product requirements

- `research-desk/app/desk.tsx` contains the watchlist, squeeze view, notes, data edits, logos and stock detail dialog.
- `research-desk/app/column-header.tsx` contains the plain-English header explanations.
- `research-desk/app/research-panel.tsx` presents the thesis, price commentary and CANSLIM evidence.
- `research-desk/app/api/desk/route.ts` stores stocks, notes, research stages, manual values and target history.
- `research-desk/lib/providers.ts` retrieves prices, valuation and financial data, short interest, borrow fees and available shares. Source dates and errors are stored separately.
- `research-desk/lib/research.ts` generates the draft automatically when a ticker is added and on manual refresh. The draft covers investment fit, bull and bear cases, catalysts, invalidation, current prices and trends.
- The preferred research themes are nuclear, metal mining, robotics and medical businesses.
- The CANSLIM screen shows clear passes, partial evidence, failures and missing evidence. ETF research uses fund analysis. Tigger remains pending until its exact methodology is identified.
- The app currently uses manual refresh. Notes and sourced manual corrections persist through refreshes. Read the dashboard README for data definitions and limitations.

## Prompt to start with

> Read CURSOR_HANDOFF.md, README.md and research-desk/START-HERE.md. Inspect both apps and help me keep building this project. Explain which app each proposed change affects. Start the app I am working on locally and verify the change through its normal UI and API. Keep changes scoped to my request.

## Validation

From `research-desk/`, run `node --experimental-strip-types --test tests/providers.test.mjs tests/research.test.mjs`. After installing dependencies, use `pnpm exec tsc --noEmit` and `pnpm build`. The existing trading-statistics checks are in the root `tests/` folder.
