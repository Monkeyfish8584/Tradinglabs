# Ollie’s Research Desk

A private stock valuation and short-squeeze research workspace, hosted with Sites.

- Add a Yahoo Finance ticker; refresh one stock or the whole list manually.
- Price, daily change, three-month chart, analyst target average/range, upside, EPS TTM, forward P/E, growth estimates and 52-week context.
- Short interest as a percentage of float, shares short, prior reporting period, days to cover, IBKR borrow cost and availability, volume comparison and reporting dates.
- Persistent watchlist, research stages, notes and sourced manual overrides in D1.
- Browser CSV export and source-level refresh status.
- No scheduling, background refresh, broker connections, order entry or paid API keys.

## Data conventions

Yahoo Finance supplies regular-session prices and chart history. Stock Analysis supplies valuation, financial statistics and short-interest statistics. ChartExchange supplies IBKR borrow snapshots and independent SI share counts/dates. Public pages and endpoints are not guaranteed feeds and may change or reject requests. Each source is refreshed separately. Failures retain previously fetched values and their original source timestamps; unavailable values are not represented as zero.

The target is the **average** 12-month analyst target, not an estimate of intrinsic fair value. Median, low and high targets appear in the stock detail. EPS TTM is distinct from forward P/E. A large target gap means 50% or more upside to the average analyst target. Target history starts with saved snapshots.

Short-float percentage and days to cover use Stock Analysis definitions. A ChartExchange settlement date is attached only if the exact reported short share count matches; a disagreement in float estimates is flagged. Borrow fee is annualised, availability represents only IBKR inventory, and borrow observation time is distinct from fetch time. Missing broker data does not imply zero inventory. The volume ratio is day volume divided by the provider’s 20-day average and is not time-of-day adjusted.

The five squeeze checks are transparent heuristics, not squeeze probabilities: short float >=20%, days to cover >=3, borrow fee >=10%, available shares <=100,000 and day-volume / 20-day average >=1.5. Unknown data remains unknown.

Manual overrides carry a source and observation time, survive refreshes, and can be cleared. The application is owner-private; the Sites access boundary protects the shared single-owner workspace. Preserve that audience. Do not make the application public without adding application-level authorization for all reads and writes.

## Development and validation

Follow the Sites skill for dependency setup, preview, builds, source synchronization and publication. Source lives in `app/`, provider parsing in `lib/providers.ts`, table definitions in `db/schema.ts`, and generated migrations in `drizzle/`.

Run:

```sh
node --experimental-strip-types --test tests/providers.test.mjs
node node_modules/typescript/bin/tsc --noEmit
```

The initial watchlist contains dated public snapshots for USAR, IBRX, ALMU, NVO, UUUU and SMR. It is seeded once on first use, so deleted tickers stay deleted. New publication does not overwrite the user’s persistent watchlist or notes.

## Automatic investment research

Adding a ticker fetches the company profile, quarterly and annual financials, current price and one-year daily history, market benchmark and recent headline links, then generates and persists the investment-research draft before returning the new stock. No model/API key or scheduled task is required. Manual refresh regenerates the draft; user-authored notes and manual corrections are preserved.

The draft uses a transparent data-driven research engine: business-specific playbooks for the initial watchlist, sector playbooks and live retrieved evidence for arbitrary new tickers. It is a potential thesis with explicit assumptions, catalysts to verify, risks and invalidation conditions; it is not a claim that an AI analyst opened and verified each linked news article. Company descriptions are used for classification, not republished. Investment preferences emphasize nuclear, metal mining, robotics and medical businesses, early improving-business opportunities, valuation discipline, cash/dilution and price confirmation.

Price research uses completed daily sessions for moving averages, RSI, returns and the 20-session price range, while the current quote has its own timestamp. One-year stock-versus-SPY price returns use overlapping dates and require enough history. Intraday volume is explicitly incomplete.

The CANSLIM screen counts **clear passes out of seven**, with partial, failed and unknown criteria shown separately. It does not invent proprietary IBD Composite/RS ratings, institutional fund quality/trends or follow-through days. Growth comparisons use actual completed annual periods and the same quarter a year earlier. Turning from a loss to profit is not represented as infinite percentage growth. "Tigger" from The Trader’s Handbook remains unscored until the exact author/criteria can be verified.
