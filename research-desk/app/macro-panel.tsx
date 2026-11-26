"use client";
import { useEffect, useState } from "react";
import { ExternalLink, RefreshCw, TrendingUp } from "lucide-react";
import type { MacroData, TimeframeTrend } from "../lib/macro";

const em = "—";
function TrendBadge({ t, label }: { t?: TimeframeTrend; label: string }) {
  if (!t) return <span className="pill neutral">{label}: {em}</span>;
  const cls = t.label === "Bullish" ? "green" : t.label === "Bearish" ? "amber" : "neutral";
  return <span className={`pill ${cls}`} title={t.note}>{label}: {t.label}{t.changePct != null ? ` ${t.changePct > 0 ? "+" : ""}${t.changePct.toFixed(1)}%` : ""}</span>;
}

export default function MacroPanel() {
  const [macro, setMacro] = useState<MacroData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  async function load() {
    try { const r = await fetch("/api/macro", { cache: "no-store" }); const d = await r.json(); setMacro(d.macro || null); } catch (e) { setError((e as Error).message); } finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);
  async function refresh() {
    setRefreshing(true); setError("");
    try { const r = await fetch("/api/macro", { method: "POST" }); const d = await r.json(); if (!r.ok) throw new Error(d.error || "Macro refresh failed"); setMacro(d.macro); } catch (e) { setError((e as Error).message); } finally { setRefreshing(false); }
  }
  const bullish = macro?.instruments.filter(i => i.daily?.label === "Bullish").length ?? 0;
  const total = macro?.instruments.length ?? 0;
  return <section className="macro-panel" aria-label="Macro view">
    <div className="panel-heading"><div><h2>Macro view — trend & breadth</h2><p>Separate from individual stocks. Weekly, daily and 4-hour trend, plus how many constituents are near new highs or lows. Bullish = close up on the period and above its 20-period average; Bearish = close down and below it; otherwise Mixed.</p></div><button className="button secondary" onClick={refresh} disabled={refreshing || loading}><RefreshCw size={14} className={refreshing ? "spin" : ""} />{refreshing ? "Refreshing macro…" : "Refresh macro"}</button></div>
    {loading ? <p className="muted">Loading macro data…</p> : !macro ? <div className="empty-state"><TrendingUp size={24} /><h3>No macro data yet</h3><p>Fetch the index and currency trends to see the health of the move.</p><button className="button secondary" onClick={refresh}>Fetch macro data</button></div> : <>
      <p className="muted">Last fetched {macro.fetchedAt ? new Date(macro.fetchedAt).toLocaleString("en-GB", { timeZone: "Europe/London", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "unknown"} UK · {bullish} of {total} instruments Bullish on the daily timeframe · Macro data is cached for 10 minutes between refreshes.</p>
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="macro-grid">
        {macro.instruments.map(inst => <article className="macro-card" key={inst.id}>
          <div className="section-title"><h3>{inst.label} <small>{inst.kind === "fx" ? "Currency" : "Index"}</small></h3><span>{inst.price != null ? inst.price.toLocaleString("en-GB", { maximumFractionDigits: 2 }) : em}{inst.changePct != null ? ` (${inst.changePct > 0 ? "+" : ""}${inst.changePct.toFixed(1)}%)` : ""}</span></div>
          {inst.error ? <p className="source-error">Trend unavailable: {inst.error}</p> : <div className="trend-badges"><TrendBadge t={inst.weekly} label="Weekly" /><TrendBadge t={inst.daily} label="Daily" /><TrendBadge t={inst.fourHour} label="4-hour" /></div>}
          <p className="muted">{inst.asOf ? `Last completed candle ${inst.asOf}` : "No completed candles"}</p>
          {!!inst.headlines?.length && <div className="thesis-headlines"><span>NEWS · GOOGLE NEWS RSS</span>{inst.headlines.map((h, i) => <a key={i} href={h.url} target="_blank" rel="noreferrer"><div>{h.title}<small>{h.date || "Date unavailable"}</small></div><ExternalLink size={13} /></a>)}</div>}
          {!inst.headlines?.length && <p className="muted">News unavailable for {inst.label}.</p>}
        </article>)}
      </div>
      <div className="section-title"><h3>Market breadth — new highs vs new lows</h3></div>
      <p className="muted">{macro.breadthNote}</p>
      <div className="macro-grid">
        {macro.breadth.map(b => <article className="macro-card" key={b.index}>
          <div className="section-title"><h3>{b.label}</h3><span>{b.coverage}</span></div>
          {b.error ? <p className="source-error">Breadth unavailable: {b.error}</p> : <div className="detail-stats">
            <div className="fact"><span>Near new highs</span><strong>{b.highs}</strong><small>within 1% of 52-week high</small></div>
            <div className="fact"><span>Near new lows</span><strong>{b.lows}</strong><small>within 1% of 52-week low</small></div>
            <div className="fact"><span>Neither</span><strong>{b.neither}</strong></div>
            <div className="fact"><span>Unavailable</span><strong>{b.unavailable}</strong><small>no quote returned</small></div>
          </div>}
          <p className="muted">{b.asOf ? `As of ${new Date(b.asOf).toLocaleString("en-GB", { timeZone: "Europe/London", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })} UK` : "Not yet fetched"}</p>
        </article>)}
      </div>
    </>}
  </section>;
}
