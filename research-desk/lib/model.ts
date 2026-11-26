export type SourceStatus = { name: string; url: string; fetchedAt?: string; asOf?: string; error?: string };
export type Snapshot = {
  ticker: string; name: string; currency?: string; exchange?: string; instrumentType?: string; price?: number; changePct?: number; quoteAt?: string;
  high52?: number; low52?: number; volume?: number; averageVolume?: number; relativeVolume?: number; closes?: number[]; closeDates?: string[];
  target?: number; targetMedian?: number; targetLow?: number; targetHigh?: number; analystCount?: number; consensus?: string;
  eps?: number; forwardPE?: number; epsGrowth?: number; marketCap?: number; float?: number; sharesOutstanding?: number; earningsDate?: string;
  shortShares?: number; shortPrevious?: number; shortFloatPct?: number; daysToCover?: number; shortDate?: string; shortPreviousDate?: string; shortChangePct?: number;
  borrowFee?: number; available?: number; borrowAt?: string; floatDisagreement?: boolean;
  sector?: string; industry?: string; companyWebsite?: string; themes?: string[]; businessFocus?: string;
  revenue?: number; freeCashFlow?: number; cash?: number; totalDebt?: number; shareChangeYoY?: number; institutionalPct?: number;
  latestQuarter?: string; quarterEPS?: number; priorYearQuarterEPS?: number; quarterRevenueGrowth?: number; quarterEPSGrowth?: number;
  annualEPS?: {period:string;eps:number|null}[]; financialCurrency?: string;
  priceHistory?: {date:string;open?:number;close:number;high:number;low:number;volume:number}[]; sessionComplete?: boolean;
  insiderTrades?: {date:string;insider:string;role?:string;type:'buy'|'sell'|'other';shares?:number;price?:number;value?:number;sourceUrl?:string}[];
  congressTrades?: {date:string;politician:string;chamber?:string;type:'buy'|'sell'|'other';amountRange?:string;price?:number;sourceUrl?:string}[];
  benchmark?: {symbol:string;price:number;closes:number[];dates:string[];quoteAt?:string};
  headlines?: {title:string;url:string;date?:string}[];
  sources: Record<string, SourceStatus>; attemptedAt?: string;
};
export type ManualValue = { value: number | string; source: string; asOf: string };
export type Stock = {
  ticker: string; name: string; addedAt: string; snapshot: Snapshot; notes: string; stage: string;
  manual: Record<string, ManualValue>; history: { recordedAt: string; target: number }[];
  research?: Research;
};
export const THESIS_START = "<!-- THESIS -->";
export const THESIS_END = "<!-- END THESIS -->";
// The "Thesis" box on the stock detail page is stored inside the existing
// notes column, as plain text between the markers above — no new table,
// column or API action. parseThesis splits it back out; the Notes tab only
// ever shows the free-text rest, and a refresh never touches it (unlike the
// auto-generated research, which is regenerated on refresh). A malformed
// block is never deleted: it is returned as ordinary notes.
export function parseThesis(notes: string): { thesis: string; rest: string } {
  const start = notes.indexOf(THESIS_START);
  if (start < 0) return { thesis: "", rest: notes };
  const end = notes.indexOf(THESIS_END, start);
  if (end < 0) return { thesis: "", rest: notes };
  const thesis = notes.slice(start + THESIS_START.length, end).trim().slice(0, 6000);
  const rest = (notes.slice(0, start) + notes.slice(end + THESIS_END.length)).replace(/\n{3,}/g, "\n\n").trim();
  return { thesis, rest };
}
export function serializeThesis(thesis: string, notes: string): string {
  const { rest } = parseThesis(notes);
  const clean = thesis.trim();
  if (!clean) return rest;
  const block = `${THESIS_START}\n${clean}\n${THESIS_END}`;
  const combined = rest ? `${rest}\n\n${block}` : block;
  return combined.slice(0, 12000);
}
export type Criterion = {letter:string;name:string;status:"pass"|"partial"|"fail"|"unknown";evidence:string;sourceKeys:string[]};
export type Research = {
  version:number; generatedAt:string; quoteAt?:string; themes:string[]; title:string; summary:string; styleFit:string;
  bullCase:string[]; bearCase:string[]; catalysts:string[]; invalidation:string[];
  priceCommentary:string[]; technicals:{trend:string;sma20?:number;sma50?:number;sma200?:number;return1m?:number;return3m?:number;return1y?:number;return5y?:number;rsi14?:number;support?:number;resistance?:number;relativeReturn?:number};
  radar?: {axis:string;score:number|null;note:string}[];
  canslim:{criteria:Criterion[];passes:number;partial:number;fails:number;unknown:number;verdict:string;notApplicable?:boolean};
  limitations:string[];
};
export const SEED_TICKERS = ["USAR", "IBRX", "ALMU", "NVO", "UUUU", "SMR"];
export const STAGES = ["Watching", "Researching", "On my shortlist", "Holding"];
export const MANUAL_NUMBERS = ["price", "target", "eps", "forwardPE", "shortFloatPct", "shortShares", "daysToCover", "borrowFee", "available"];
export function effective(stock: Pick<Stock,"snapshot"|"manual">): Snapshot {
  const s = { ...stock.snapshot };
  for (const [key, m] of Object.entries(stock.manual)) (s as any)[key] = m.value;
  if (stock.manual.price) { s.quoteAt = stock.manual.price.asOf; s.changePct = undefined; }
  if (stock.manual.borrowFee || stock.manual.available) s.borrowAt = (stock.manual.borrowFee || stock.manual.available).asOf;
  return s;
}
export function upside(s: Snapshot) { return s.price && s.target && s.price > 0 ? (s.target / s.price - 1) * 100 : null; }
export function squeezeChecks(s: Snapshot) {
  const data = [
    { label: "Short float ≥ 20%", value: s.shortFloatPct, test: (n: number) => n >= 20 },
    { label: "Days to cover ≥ 3", value: s.daysToCover, test: (n: number) => n >= 3 },
    { label: "Borrow fee ≥ 10%", value: s.borrowFee, test: (n: number) => n >= 10 },
    { label: "Available shares ≤ 100k", value: s.available, test: (n: number) => n <= 100000 },
    { label: "Day volume / 20d avg ≥ 1.5×", value: s.relativeVolume, test: (n: number) => n >= 1.5 },
  ];
  return data.map(c => ({ ...c, known: c.value != null, passed: c.value != null && c.test(c.value) }));
}
export function validTicker(t: unknown): t is string { return typeof t === "string" && /^[A-Z0-9][A-Z0-9.^=-]{0,14}$/.test(t); }

