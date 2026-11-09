import type { Snapshot } from "./model";
const UA = "Mozilla/5.0 (compatible; ResearchDesk/1.0)";
import {numberValue,tableRows,textOnly} from "./parsing.ts";
export {numberValue,tableRows,textOnly} from "./parsing.ts";
import {parseProfile,parseQuarterly,parseAnnual,parseHeadlines} from "./research-data.ts";
export function parseStatistics(html: string): Partial<Snapshot> {
  const values = new Map(tableRows(html).filter(r => r.length === 2).map(r => [r[0].text.trim(), r[1]]));
  const val = (...labels: string[]) => { const c = labels.map(l => values.get(l)).find(Boolean); return numberValue(c?.raw.match(/title="([^"]+)"/)?.[1] ?? c?.text); };
  if (!values.has("Market Cap") || !values.has("Shares Outstanding")) throw new Error("Statistics not available for this ticker");
  return {
    marketCap: val("Market Cap"), target: val("Price Target"), eps: val("Earnings Per Share (EPS)", "Earnings Per Share", "Loss Per Share"), forwardPE: val("Forward PE"),
    analystCount: val("Analyst Count"), consensus: values.get("Analyst Consensus")?.text, epsGrowth: val("EPS Growth Forecast (3Y)"),
    float: val("Float"), sharesOutstanding: val("Shares Outstanding"), shortShares: val("Short Interest"), shortPrevious: val("Short Previous Month"),
    shortFloatPct: val("Short % of Float"), daysToCover: val("Short Ratio (days to cover)"), averageVolume: val("Average Volume (20 Days)"), earningsDate: values.get("Earnings Date")?.text,
    revenue:val("Revenue"), freeCashFlow:val("Free Cash Flow"), cash:val("Cash & Cash Equivalents"), totalDebt:val("Total Debt"),
    shareChangeYoY:val("Shares Change (YoY)"),institutionalPct:val("Owned by Institutions (%)"),
  };
}
export function parseForecast(html: string): Partial<Snapshot> {
  const rows = tableRows(html), i = rows.findIndex(r => r[0]?.text === "Target" && r[1]?.text === "Low" && r[2]?.text === "Average");
  const row = rows[i + 1];
  if (i < 0 || row?.[0]?.text !== "Price") throw new Error("Analyst target range unavailable");
  return { targetLow: numberValue(row[1]?.text), target: numberValue(row[2]?.text), targetMedian: numberValue(row[3]?.text), targetHigh: numberValue(row[4]?.text) };
}
export function easternISO(text: string): string | undefined {
  const m = text.match(/(\d{4}-\d\d-\d\d) (\d{1,2}):(\d\d):(\d\d) (AM|PM) (EDT|EST)/);
  if (!m) return undefined;
  const hour = (Number(m[2]) % 12) + (m[5] === "PM" ? 12 : 0);
  return new Date(`${m[1]}T${String(hour).padStart(2,"0")}:${m[3]}:${m[4]}${m[6] === "EDT" ? "-04:00" : "-05:00"}`).toISOString();
}
export function parseBorrow(html: string): Partial<Snapshot> {
  const block = html.match(/<p[^>]*class="[^"]*\bbf-summary\b[^"]*"[^>]*>([\s\S]*?)<\/p>/)?.[1];
  if (!block) throw new Error("No current IBKR borrow snapshot published");
  const match = textOnly(block).match(/As of (.+?), there were ([\d,]+) shares available with a fee of ([\d.]+)\s*%/);
  if (!match) throw new Error("Borrow snapshot could not be read");
  const borrowAt = easternISO(match[1]);
  if (!borrowAt) throw new Error("Borrow timestamp unavailable");
  return { borrowAt, available: numberValue(match[2]), borrowFee: numberValue(match[3]) };
}
export function parseReportedShort(html: string, stats: Partial<Snapshot>): Partial<Snapshot> {
  const rows = tableRows(html).filter(r => /^\d{4}-\d\d-\d\d$/.test(r[0]?.text || "") && r.length >= 8);
  const r = rows[0], prev = rows[1];
  if (!r) throw new Error("Short-interest settlement date unavailable");
  const reported = numberValue(r[2].text);
  if (reported == null || stats.shortShares == null || Math.abs(reported - stats.shortShares) > 1) throw new Error("Sources differ: settlement date not verified");
  return { shortDate: r[0].text, shortPrevious: prev ? numberValue(prev[2].text) : undefined, shortPreviousDate: prev?.[0]?.text,
    shortChangePct: numberValue(r[5]?.text), floatDisagreement: stats.shortFloatPct != null && Math.abs((numberValue(r[1]?.text) ?? stats.shortFloatPct) - stats.shortFloatPct) > 5 };
}
async function fetchText(url: string): Promise<string> {
  const r = await fetch(url, { headers: { "User-Agent": UA, Accept: "text/html,application/json" }, signal: AbortSignal.timeout(16000) });
  if (!r.ok) throw new Error(r.status === 429 ? "Provider rate limit; try again later" : r.status === 403 ? "Provider blocked this request" : `Provider returned HTTP ${r.status}`);
  const body = await r.text();
  if (body.length < 100) throw new Error("Provider returned an incomplete response");
  return body;
}
export async function refreshSnapshot(ticker: string, previous?: Snapshot): Promise<Snapshot> {
  const now = new Date().toISOString();
  const foreign=ticker.match(/^(.+)\.(DE|MC|PA)$/),market:Record<string,string>={DE:'etr',MC:'bme',PA:'epa'};
  const equityBase=foreign?`https://stockanalysis.com/quote/${market[foreign[2]]}/${encodeURIComponent(foreign[1])}`:`https://stockanalysis.com/stocks/${ticker.toLowerCase()}`;
  const out: Snapshot = { ...(previous || {}), ticker, name: previous?.name || ticker, sources: { ...previous?.sources }, attemptedAt: now };
  const source = async (key: string, name: string, url: string, read: (body: string) => Partial<Snapshot>) => {
    try {
      const result = read(await fetchText(url));
      if (key === "stats" && result.shortShares !== out.shortShares) {
        out.shortDate = undefined; out.shortPreviousDate = undefined; out.shortChangePct = undefined; out.floatDisagreement = undefined;
      }
      // Prefer the explicit consensus table if the statistics request finishes later.
      if (key === "stats" && out.sources.forecast?.fetchedAt === now) delete result.target;
      Object.assign(out, result);
      out.sources[key] = { name, url, fetchedAt: now, asOf: key === "quote" ? out.quoteAt : key === "borrow" ? out.borrowAt : key === "short" ? out.shortDate : undefined };
    } catch (e) {
      const message = e instanceof Error ? e.message : "Source unavailable";
      out.sources[key] = { ...out.sources[key], name, url, error: /internal error|fetch failed|network|connection|timeout|aborted/i.test(message) ? "Feed could not be reached; try again later" : message };
    }
  };
  await Promise.all([
    source("quote", "Yahoo Finance", `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}?interval=1d&range=1y`, body => {
      const c = JSON.parse(body).chart?.result?.[0];
      if (!c || !Number.isFinite(c.meta?.regularMarketPrice)) throw new Error("Ticker not found or quote unavailable");
      const m = c.meta, q = c.indicators.quote[0];
      const points = (c.timestamp || []).map((t: number, i: number) => ({ date: new Date(t * 1000).toISOString().slice(0,10), close: q.close[i], high: Number.isFinite(q.high?.[i])?q.high[i]:q.close[i], low:Number.isFinite(q.low?.[i])?q.low[i]:q.close[i], volume: q.volume[i] })).filter((p: any) => Number.isFinite(p.close));
      const avg = points.slice(-21,-1).map((p: any) => p.volume).filter(Number.isFinite);
      const averageVolume = avg.length >= 10 ? avg.reduce((a: number,b: number) => a+b,0)/avg.length : undefined;
      const prevClose = points.length > 1 ? points.at(-2).close : undefined;
      return { name: m.longName || m.shortName || ticker, currency: m.currency, exchange: m.exchangeName, instrumentType: m.instrumentType, price: m.regularMarketPrice,
        changePct: Number.isFinite(m.regularMarketChangePercent) ? m.regularMarketChangePercent : prevClose ? (m.regularMarketPrice / prevClose - 1) * 100 : undefined,
        quoteAt: m.regularMarketTime ? new Date(m.regularMarketTime * 1000).toISOString() : undefined, high52: m.fiftyTwoWeekHigh, low52: m.fiftyTwoWeekLow,
        volume: m.regularMarketVolume, closes: points.slice(-63).map((p: any) => p.close), closeDates: points.slice(-63).map((p: any) => p.date), averageVolume,priceHistory:points,sessionComplete:!!m.currentTradingPeriod?.regular?.end&&Date.now()>=m.currentTradingPeriod.regular.end*1000 };
    }),
    ...(ticker === 'NUCG.L' ? [source('fund','VanEck · fund overview','https://www.vaneck.com/uk/en/investments/nuclear-etf/overview/',body=>{
      if(!body.includes('IE000M7V94E1'))throw new Error('Fund identity could not be verified');
      return {themes:['Nuclear','Metal mining'],industry:'Nuclear and uranium equity ETF',businessFocus:'a basket of nuclear and uranium value-chain equities',companyWebsite:'https://www.vaneck.com/uk/en/investments/nuclear-etf/overview/'};
    })] : [
      source("stats", "Stock Analysis", `${equityBase}/statistics/`, parseStatistics),
      source("forecast", "Stock Analysis · analyst consensus", `${equityBase}/forecast/`, parseForecast),
      source("profile", "Stock Analysis · company profile", `${equityBase}/company/`, parseProfile),
      source("quarterly", "Stock Analysis · quarterly financials", `${equityBase}/financials/?p=quarterly`, parseQuarterly),
      source("annual", "Stock Analysis · annual financials", `${equityBase}/financials/`, parseAnnual),
      source("news", "Stock Analysis · headline index", `${equityBase}/`, parseHeadlines),
    ]),
    source("benchmark", "Yahoo Finance · SPY benchmark", "https://query1.finance.yahoo.com/v8/finance/chart/SPY?interval=1d&range=1y", body=>{
      const c=JSON.parse(body).chart?.result?.[0];if(!c||!Number.isFinite(c.meta?.regularMarketPrice))throw new Error("Market benchmark unavailable");
      const points=(c.timestamp||[]).map((t:number,i:number)=>({date:new Date(t*1000).toISOString().slice(0,10),close:c.indicators.quote[0].close[i]})).filter((p:any)=>Number.isFinite(p.close));
      return {benchmark:{symbol:"SPY",price:c.meta.regularMarketPrice,closes:points.map((p:any)=>p.close),dates:points.map((p:any)=>p.date),quoteAt:c.meta.regularMarketTime?new Date(c.meta.regularMarketTime*1000).toISOString():undefined}};
    }),
  ]);
  if (out.volume != null && out.averageVolume && out.sources.quote?.fetchedAt === now) out.relativeVolume = out.volume / out.averageVolume;
  const exchange = out.exchange === "ASE" ? "nyseamerican" : /^(NYQ|PCX)$/.test(out.exchange || "") ? "nyse" : /^(NMS|NGM|NCM|NAS|NASDAQ)$/.test(out.exchange || "") ? "nasdaq" : null;
  if (exchange) {
    const base = `https://chartexchange.com/symbol/${exchange}-${ticker.toLowerCase()}`;
    await Promise.all([source("borrow", "ChartExchange · IBKR", `${base}/borrow-fee/`, parseBorrow), source("short", "ChartExchange · reported SI date", `${base}/short-interest/`, body => parseReportedShort(body, out))]);
  }
  return out;
}
