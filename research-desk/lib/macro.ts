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
export type MacroData = {
  fetchedAt: string; instruments: MacroInstrument[]; breadth: Breadth[];
  breadthNote: string;
};

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
