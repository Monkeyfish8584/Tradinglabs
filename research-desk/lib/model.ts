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
  priceHistory?: {date:string;close:number;high:number;low:number;volume:number}[]; sessionComplete?: boolean;
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
export type Criterion = {letter:string;name:string;status:"pass"|"partial"|"fail"|"unknown";evidence:string;sourceKeys:string[]};
export type Research = {
  version:number; generatedAt:string; quoteAt?:string; themes:string[]; title:string; summary:string; styleFit:string;
  bullCase:string[]; bearCase:string[]; catalysts:string[]; invalidation:string[];
  priceCommentary:string[]; technicals:{trend:string;sma20?:number;sma50?:number;sma200?:number;return1m?:number;return3m?:number;return1y?:number;rsi14?:number;support?:number;resistance?:number;relativeReturn?:number};
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
