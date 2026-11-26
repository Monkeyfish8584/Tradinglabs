# Ollie’s Research Desk

A private stock valuation and short-squeeze research workspace, hosted with Sites.

- Add a Yahoo Finance ticker; refresh one stock or the whole list manually.
- Price, daily change, three-month chart, analyst target average/range, upside, EPS TTM, forward P/E, growth estimates and 52-week context.
- Short interest as a percentage of float, shares short, prior reporting period, days to cover, IBKR borrow cost and availability, volume comparison and reporting dates.
- Persistent watchlist, research stages, notes and sourced manual overrides in D1.
- Browser CSV export and source-level refresh status.
- Add a ticker by company name as well as by ticker (Yahoo symbol search), and open a stock's detail in a new tab with a `?stock=TICKER` deep link.
- Five years of daily price history, with a 3M / 1Y / 5Y chart in the stock overview and date-anchored 1- and 5-year returns.
- Insider trades (officer/director, with entry price where published) in the thesis and in an Insider tab. Congressional/politician trades are not available in this desk: there is no free structured feed, and disclosures are typically value ranges with no exact entry price.
- A separate macro view (below the watchlist summary, above the stock table): weekly, daily and 4-hour trend for US 100, US 500, UK 100 and DAX, the same three timeframes for EUR/USD, GBP/JPY and USD/JPY, news for each instrument (Google News RSS), and market breadth — how many constituents are within 1% of their 52-week high vs low, from Wikipedia constituent lists and Yahoo batch quotes, with coverage shown.
- A "Draft it together" speculative thesis section in the Thesis tab, alongside the automatic draft: Oliver's idea in his own words, what has to go right, what would prove it wrong, the biggest risk, the catalyst, and Muse's challenge and added detail/evidence. It is labelled speculative, never sourced data, and the automatic thesis, bull/bear case and CANSLIM are untouched. It is stored inside the existing notes column as one JSON block between `<!-- DRAFT-IT-TOGETHER: SPECULATIVE THESIS -->` markers (see `parseSpeculativeDraft` / `serializeSpeculativeDraft` in `lib/model.ts`) — no new table, column or API action — so it saves with research notes, survives refreshes, and the Notes tab never shows the block. A malformed block is treated as ordinary notes, never deleted.
- A draft heuristic spider/radar diagram in the thesis (technical, valuation, earnings quality, financial health, sentiment proxy), scored 0–10 from data already on the desk. Sentiment is a weak proxy only; an axis with missing inputs is Unavailable, never zero. The BofA Bull & Bear score is a proprietary Bank of America indicator and is not available in this desk; the breadth and trend read is the desk's own equivalent, not a BofA score.
- A macro spider diagram in the macro view (Technical × Sentiment × Fundamental, 0–10 each, from the BofA explainer guide's scoring rules): Technical from multi-timeframe trend and breadth, Sentiment read backwards (high = crowded = caution) from breadth crowdedness and trend unanimity, Fundamental averaged across the stocks on the desk (CANSLIM, earnings growth, valuation). It reads as a short verdict, e.g. 7 / 8 / 6 = "Crowded, not broken".
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

