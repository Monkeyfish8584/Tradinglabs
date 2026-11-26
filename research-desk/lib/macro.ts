// Macro view: multi-timeframe trend, market breadth and news for indices/FX.
// All data comes from the same free Yahoo chart endpoints the desk already
// uses, plus Wikipedia constituent lists and Google News RSS. Nothing here
// invents a price, a breadth count or a sentiment score: a failed fetch is
// reported as unavailable with its source and time, never as zero.
import { tableRows, textOnly } from "./parsing.ts";

export type Candle = { date: string; open?: number; high: number; low: number; close: number; volume?: number };
export type TrendLabel = "Bullish" | "Bearish" | "Mixed" | "Unavailable";
export type TimeframeTrend = { label: TrendLabel; changePct?: number; aboveSma20?: boolean; note: string };
export type MacroInstrument = {
  id: string; label: string; symbol: string; kind: "index" | "fx";
  weekly?: TimeframeTrend; daily?: TimeframeTrend; fourHour?: TimeframeTrend;
  price?: number; changePct?: number; asOf?: string; error?: string;
  headlines?: { title: string; url: string; date?: string }[];
};
export type Breadth = {
  index: string; label: string; asOf?: string; total: number; highs: number; lows: number;
  neither: number; unavailable: number; coverage: string; error?: string;
};
export type MacroSpiderAxis = { axis: "Technical" | "Sentiment" | "Fundamental"; score: number | null; note: string };
export type MacroSpider = { axes: MacroSpiderAxis[]; verdict: string; verdictNote: string };
export type MacroData = {
  fetchedAt: string; instruments: MacroInstrument[]; breadth: Breadth[];
  breadthNote: string; spider?: MacroSpider;
};
export type StockFundamental = { canslimPasses?: number; quarterEPSGrowth?: number; forwardPE?: number };

export const MACRO_INSTRUMENTS: { id: string; label: string; symbol: string; kind: "index" | "fx" }[] = [
  { id: "us100", label: "US 100", symbol: "^NDX", kind: "index" },
  { id: "us500", label: "US 500", symbol: "^GSPC", kind: "index" },
  { id: "uk100", label: "UK 100", symbol: "^FTSE", kind: "index" },
  { id: "dax", label: "DAX", symbol: "^GDAXI", kind: "index" },
  { id: "eurusd", label: "EUR/USD", symbol: "EURUSD=X", kind: "fx" },
  { id: "gbpjpy", label: "GBP/JPY", symbol: "GBPJPY=X", kind: "fx" },
  { id: "usdjpy", label: "USD/JPY", symbol: "USDJPY=X", kind: "fx" },
];

export const BREADTH_INDICES: { id: string; label: string; symbol: string; listUrl: string }[] = [
  { id: "us100", label: "US 100", symbol: "^NDX", listUrl: "https://en.wikipedia.org/wiki/NASDAQ-100" },
  { id: "us500", label: "US 500", symbol: "^GSPC", listUrl: "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies" },
  { id: "uk100", label: "UK 100", symbol: "^FTSE", listUrl: "https://en.wikipedia.org/wiki/FTSE_100_Index" },
  { id: "dax", label: "DAX", symbol: "^GDAXI", listUrl: "https://en.wikipedia.org/wiki/DAX" },
];

const UA = "Mozilla/5.0 (compatible; ResearchDesk/1.0)";
async function fetchText(url: string): Promise<string> {
  const r = await fetch(url, { headers: { "User-Agent": UA, Accept: "text/html,application/json" }, signal: AbortSignal.timeout(16000) });
  if (!r.ok) throw new Error(r.status === 429 ? "Provider rate limit; try again later" : `Provider returned HTTP ${r.status}`);
  const body = await r.text();
  if (body.length < 100) throw new Error("Provider returned an incomplete response");
  return body;
}

export function sma(values: number[], period: number): number | undefined {
  return values.length >= period ? values.slice(-period).reduce((a, b) => a + b, 0) / period : undefined;
}

export async function fetchChart(symbol: string, interval: string, range: string): Promise<Candle[]> {
  const body = await fetchText(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?interval=${interval}&range=${range}`);
  const c = JSON.parse(body).chart?.result?.[0];
  if (!c) throw new Error("Chart unavailable");
  const q = c.indicators.quote[0];
  const now = Date.now();
  return (c.timestamp || []).map((t: number, i: number) => ({
    date: new Date(t * 1000).toISOString().slice(0, 10),
    open: q.open?.[i], high: q.high?.[i], low: q.low?.[i], close: q.close[i], volume: q.volume?.[i],
    _ts: t * 1000,
  } as Candle & { _ts: number }))
    .filter((p: any) => Number.isFinite(p.close) && Number.isFinite(p.high) && Number.isFinite(p.low) && p._ts < now)
    .map(({ _ts, ...p }: any) => p);
}

export function aggregate4h(hourly: Candle[]): Candle[] {
  const out: Candle[] = [];
  for (let i = 0; i + 3 < hourly.length; i += 4) {
    const g = hourly.slice(i, i + 4);
    out.push({ date: g[3].date, open: g[0].open, high: Math.max(...g.map(x => x.high)), low: Math.min(...g.map(x => x.low)), close: g[3].close, volume: g.reduce((a, x) => a + (x.volume || 0), 0) });
  }
  return out;
}

export function trendFor(candles: Candle[]): TimeframeTrend {
  const closes = candles.map(c => c.close);
  if (closes.length < 21) return { label: "Unavailable", note: "Fewer than 21 completed candles." };
  const latest = closes.at(-1)!, prev = closes.at(-2)!;
  const s20 = sma(closes, 20);
  if (s20 == null) return { label: "Unavailable", note: "No 20-period average." };
  const changePct = prev > 0 ? (latest / prev - 1) * 100 : undefined;
  const above = latest > s20;
  const label: TrendLabel = latest > prev && above ? "Bullish" : latest < prev && !above ? "Bearish" : "Mixed";
  return { label, changePct, aboveSma20: above, note: `${label === "Bullish" ? "Close up on the period and above its 20-period average" : label === "Bearish" ? "Close down on the period and below its 20-period average" : "Close and 20-period average disagree"}.` };
}

async function fetchNews(query: string): Promise<MacroInstrument["headlines"]> {
  const xml = await fetchText(`https://news.google.com/rss/search?q=${encodeURIComponent(query)}&hl=en-GB&gl=GB&ceid=GB:en`);
  const items: { title: string; url: string; date?: string }[] = [];
  for (const m of xml.matchAll(/<item>([\s\S]*?)<\/item>/gi)) {
    const title = m[1].match(/<title>([\s\S]*?)<\/title>/i)?.[1]?.replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1").trim();
    const url = m[1].match(/<link>([\s\S]*?)<\/link>/i)?.[1]?.trim();
    const date = m[1].match(/<pubDate>([\s\S]*?)<\/pubDate>/i)?.[1]?.trim();
    if (title && url) items.push({ title: textOnly(title), url, date });
    if (items.length >= 5) break;
  }
  return items;
}

function parseConstituents(html: string): string[] {
  const rows = tableRows(html);
  const out: string[] = [];
  let started = false;
  for (const r of rows) {
    const cells = r.map(c => c.text.trim());
    if (!started) {
      if (cells.some(c => /^(symbol|ticker)$/i.test(c))) { started = true; }
      continue;
    }
    const sym = cells[0]?.replace(".", "-").toUpperCase();
    if (/^[A-Z0-9][A-Z0-9\-]{0,9}$/.test(sym) && !out.includes(sym)) out.push(sym);
    if (out.length >= 600) break;
  }
  return out;
}

async function fetchBreadth(idx: (typeof BREADTH_INDICES)[number]): Promise<Breadth> {
  const base: Breadth = { index: idx.id, label: idx.label, total: 0, highs: 0, lows: 0, neither: 0, unavailable: 0, coverage: "0 of 0 fetched" };
  try {
    const tickers = parseConstituents(await fetchText(idx.listUrl));
    if (!tickers.length) return { ...base, error: "Constituent list could not be read." };
    let highs = 0, lows = 0, neither = 0, unavailable = 0;
    // Yahoo batch quote: up to ~100 symbols per request. A "new high" here
    // is a price within 1% of its 52-week high (and a new low within 1% of
    // its 52-week low) — labelled as such in the UI, not a 1-year-high close.
    for (let i = 0; i < tickers.length; i += 100) {
      const batch = tickers.slice(i, i + 100);
      try {
        const data: any = JSON.parse(await fetchText(`https://query1.finance.yahoo.com/v7/finance/quote?symbols=${encodeURIComponent(batch.join(","))}`));
        for (const q of data?.quoteResponse?.result || []) {
          const price = q.regularMarketPrice, hi = q.fiftyTwoWeekHigh, lo = q.fiftyTwoWeekLow;
          if (price == null || hi == null || lo == null) { unavailable++; continue; }
          if (price >= hi * 0.995) highs++;
          else if (price <= lo * 1.005) lows++;
          else neither++;
        }
      } catch { unavailable += batch.length; }
    }
    const total = highs + lows + neither + unavailable;
    return { ...base, asOf: new Date().toISOString(), total, highs, lows, neither, unavailable, coverage: `${total - unavailable} of ${total} fetched` };
  } catch (e) {
    return { ...base, error: e instanceof Error ? e.message : "Breadth unavailable" };
  }
}

export async function refreshMacro(): Promise<MacroData> {
  const instruments: MacroInstrument[] = await Promise.all(MACRO_INSTRUMENTS.map(async (inst) => {
    const out: MacroInstrument = { ...inst };
    try {
      const [daily, weekly, hourly] = await Promise.all([
        fetchChart(inst.symbol, "1d", "1y"),
        fetchChart(inst.symbol, "1wk", "5y"),
        fetchChart(inst.symbol, "60m", "1mo"),
      ]);
      out.daily = trendFor(daily);
      out.weekly = trendFor(weekly);
      out.fourHour = trendFor(aggregate4h(hourly));
      const last = daily.at(-1);
      out.price = last?.close;
      out.changePct = daily.length > 1 && daily.at(-2)!.close > 0 ? (last!.close / daily.at(-2)!.close - 1) * 100 : undefined;
      out.asOf = last?.date;
    } catch (e) {
      out.error = e instanceof Error ? e.message : "Macro data unavailable";
    }
    try { out.headlines = await fetchNews(`${inst.label} index market news`); } catch { out.headlines = []; }
    return out;
  }));
  const breadth = await Promise.all(BREADTH_INDICES.map(fetchBreadth));
  return {
    fetchedAt: new Date().toISOString(), instruments, breadth,
    breadthNote: "New high = price within 1% of its 52-week high; new low = within 1% of its 52-week low. Counts are from Yahoo batch quotes against Wikipedia constituent lists, as of the fetch time. The BofA Bull & Bear score is a proprietary Bank of America indicator and is not available in this desk — the breadth and trend read above is the desk's own equivalent, not a BofA score.",
  };
}

// ---------------------------------------------------------------------------
// Macro spider diagram — Technical × Sentiment × Fundamental, 0–10 each.
// Scoring rules from the BofA explainer guide (artifact
// bofa-score-and-spider-diagram). The guide gives directional rules, not a
// complete arithmetic specification ("~1 point per bullish timeframe,
// scaled", "full/partial/zero"), so the point allocation below is the desk's
// deterministic implementation of those rules, stated in full here and in
// the UI. Sentiment is read backwards: a high score means crowded = caution,
// not a buy signal.
//   Technical (10): daily trend 4 + weekly trend 3 + 4-hour trend 1 + breadth 2.
//     Each trend component is the share of the 7 tracked instruments that are
//     Bullish on that timeframe, scaled to its points. Breadth is the average
//     net breadth (highs − lows) / total across the four indices, mapped so
//     net −0.20 → 0 and net +0.20 → 2. If net breadth is negative while the
//     indices are up, Technical is capped at 6 (the guide's breadth cap).
//   Sentiment (10): breadth crowdedness 5 + daily-trend unanimity 3 +
//     weekly-trend unanimity 2. Breadth crowdedness is the average share of
//     constituents near new highs, mapped 0 → 0 and 0.30 → 5. This is a
//     breadth/trend proxy only: there is no put/call ratio or live BofA
//     reading in this desk, and the guide's last reported BofA figure
//     (~7.1, early Nov 2026) is a stale press snapshot, not live data, so
//     it is not used as an input.
//   Fundamental (10): averaged across the stocks on the desk (not the
//     indices themselves). CANSLIM passes/7 × 5 + share of stocks with
//     quarterly EPS growth ≥ 25% × 3 + share with forward P/E < 20 × 2.
//     Cheap alone does not earn a high score without growth, per the guide.
//   An axis with no usable inputs is null (Unavailable), never zero.
export function computeMacroSpider(macro: MacroData, stocks: StockFundamental[]): MacroSpider {
  const clamp = (n: number) => Math.max(0, Math.min(10, Math.round(n)));
  const bullishShare = (tf: "weekly" | "daily" | "fourHour") => {
    const xs = macro.instruments.filter(i => i[tf]);
    return xs.length ? xs.filter(i => i[tf]!.label === "Bullish").length / xs.length : null;
  };
  const d = bullishShare("daily"), w = bullishShare("weekly"), h = bullishShare("fourHour");
  const netBreadth = macro.breadth.length ? macro.breadth.filter(b => !b.error && b.total > 0).map(b => (b.highs - b.lows) / b.total) : [];
  const net = netBreadth.length ? netBreadth.reduce((a, b) => a + b, 0) / netBreadth.length : null;
  const nearHighs = macro.breadth.length ? macro.breadth.filter(b => !b.error && b.total > 0).map(b => b.highs / b.total) : [];
  const crowded = nearHighs.length ? nearHighs.reduce((a, b) => a + b, 0) / nearHighs.length : null;
  let technical: number | null = null;
  if (d != null || w != null || h != null || net != null) {
    technical = clamp((d ?? 0) * 4 + (w ?? 0) * 3 + (h ?? 0) * 1 + (net == null ? 0 : Math.max(0, Math.min(1, (net + 0.2) / 0.4)) * 2));
    if (net != null && net < 0 && (d ?? 0) > 0.5 && technical > 6) technical = 6;
  }
  let sentiment: number | null = null;
  if (crowded != null || d != null || w != null) {
    sentiment = clamp((crowded == null ? 0 : Math.min(1, crowded / 0.3) * 5) + (d ?? 0) * 3 + (w ?? 0) * 2);
  }
  let fundamental: number | null = null;
  if (stocks.length) {
    const withCanslim = stocks.filter(s => s.canslimPasses != null);
    const withGrowth = stocks.filter(s => s.quarterEPSGrowth != null);
    const withPE = stocks.filter(s => s.forwardPE != null);
    if (withCanslim.length || withGrowth.length || withPE.length) {
      const canslimPart = withCanslim.length ? (withCanslim.reduce((a, s) => a + (s.canslimPasses ?? 0), 0) / withCanslim.length / 7) * 5 : 0;
      const growthPart = withGrowth.length ? (withGrowth.filter(s => (s.quarterEPSGrowth ?? 0) >= 25).length / withGrowth.length) * 3 : 0;
      const valuePart = withPE.length ? (withPE.filter(s => (s.forwardPE ?? 99) < 20).length / withPE.length) * 2 : 0;
      fundamental = clamp(canslimPart + growthPart + valuePart);
    }
  }
  const axes: MacroSpiderAxis[] = [
    { axis: "Technical", score: technical, note: "Daily trend ×4, weekly ×3, 4-hour ×1, breadth ×2; capped at 6 if breadth is negative while indices rise." },
    { axis: "Sentiment", score: sentiment, note: "Read backwards — high = crowded = caution. Breadth crowdedness ×5, daily unanimity ×3, weekly ×2. Proxy only: no put/call ratio or live BofA reading in this desk." },
    { axis: "Fundamental", score: fundamental, note: "Averaged across stocks on the desk: CANSLIM passes ×5, quarterly EPS growth ≥25% ×3, forward P/E <20 ×2." },
  ];
  const [T, S, F] = [technical, sentiment, fundamental];
  let verdict = "Mixed — check the axes below.";
  let verdictNote = "No single shape dominates. Read the lowest axis first: that is where the setup is weakest.";
  if (T != null && S != null && F != null) {
    if (S >= 8 && F >= 6 && T >= 6) { verdict = "Crowded, not broken"; verdictNote = "Sentiment is high but fundamentals are decent and the trend is up. Everyone already likes it — expect sharp dips on any disappointment — but the underlying story looks intact. Picky entries, sensible size."; }
    else if (T < 4 && F >= 6) { verdict = "Watchlist, not a short"; verdictNote = "Technically weak but fundamentally strong. Wait for the trend to turn rather than shorting a good story."; }
    else if (T >= 7 && S >= 7 && F < 4) { verdict = "Momentum-bubble shape"; verdictNote = "Trend and crowd are hot, fundamentals are weak. Momentum can run, but there is little underneath it."; }
    else if (T < 4 && S < 4 && F < 4) { verdict = "No reason to be here yet"; verdictNote = "All three axes are low. Nothing in the setup earns attention right now."; }
    else if (T >= 5 && T <= 7 && S >= 5 && S <= 7 && F >= 5 && F <= 7) { verdict = "Healthy, well-rounded setup"; verdictNote = "A balanced triangle: trend, crowd and fundamentals are all in the middle of the range."; }
  }
  return { axes, verdict, verdictNote };
}
