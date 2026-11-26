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


function MacroSpider({ spider }: { spider: NonNullable<import("../lib/macro").MacroData["spider"]> }) {
  const cx = 140, cy = 115, R = 85;
  const point = (i: number, v: number) => { const ang = -Math.PI / 2 + i * 2 * Math.PI / 3; return `${cx + Math.cos(ang) * R * v},${cy + Math.sin(ang) * R * v}`; };
  const ring = (f: number) => [0, 1, 2].map(i => point(i, f)).join(" ");
  const pts = spider.axes.map((a, i) => point(i, (a.score ?? 0) / 10)).join(" ");
  const labels = spider.axes.map((a, i) => { const ang = -Math.PI / 2 + i * 2 * Math.PI / 3; return { x: cx + Math.cos(ang) * (R + 28), y: cy + Math.sin(ang) * (R + 28), text: `${a.axis} ${a.score == null ? "—" : a.score}/10` }; });
  return <div className="radar-diagram">
    <svg viewBox="0 0 280 230" role="img" aria-label={`Macro spider diagram: Technical ${spider.axes[0].score ?? "unavailable"}, Sentiment ${spider.axes[1].score ?? "unavailable"}, Fundamental ${spider.axes[2].score ?? "unavailable"}`}>
      <polygon points={ring(1)} fill="none" stroke="#dbe3ea" /><polygon points={ring(0.5)} fill="none" stroke="#e9eef3" />
      {[0, 1, 2].map(i => <line key={i} x1={cx} y1={cy} x2={cx + Math.cos(-Math.PI / 2 + i * 2 * Math.PI / 3) * R} y2={cy + Math.sin(-Math.PI / 2 + i * 2 * Math.PI / 3) * R} stroke="#e9eef3" />)}
      {spider.axes.every(a => a.score != null) && <polygon points={pts} fill="rgba(31,111,84,0.18)" stroke="#1f6f54" strokeWidth="2" />}
      {labels.map((l, i) => <text key={i} x={l.x} y={l.y} textAnchor="middle" fontSize="11">{l.text}</text>)}
    </svg>
    <p><strong>{spider.verdict}</strong> — {spider.verdictNote}</p>
    <table className="radar-table"><tbody>{spider.axes.map(a => <tr key={a.axis}><td>{a.axis}</td><td><strong>{a.score == null ? "Unavailable" : `${a.score}/10`}</strong></td><td className="muted">{a.note}</td></tr>)}</tbody></table>
    <p className="muted">Example from the BofA explainer guide: Technical 7, Sentiment 8, Fundamental 6 — “Crowded, not broken”. Illustrative example, not live data. Sentiment is read backwards: a high score means crowded = caution, not a buy signal.</p>
  </div>;
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
      <div className="section-title"><h3>Spider diagram — Technical × Sentiment × Fundamental</h3><span className="pill amber">Draft · heuristic</span></div>
      {macro.spider ? <MacroSpider spider={macro.spider} /> : <p className="muted">Spider diagram unavailable until the next macro refresh — it is computed from the trend, breadth and desk-fundamentals data above.</p>}
    </>}
  </section>;
}
