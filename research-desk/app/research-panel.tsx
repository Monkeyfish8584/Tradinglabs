"use client";
import {ArrowUpRight,BookOpen,Check,ChevronRight,Clock3,ExternalLink,RefreshCw,TrendingUp} from 'lucide-react';
import {composeResearch} from '../lib/research';
import {effective,type Stock} from '../lib/model';
const n=(v:number|undefined)=>v==null?'—':v.toFixed(2);
const p=(v:number|undefined)=>v==null?'—':`${v>0?'+':''}${v.toFixed(1)}%`;
const date=(v?:string)=>v?new Date(v).toLocaleString('en-GB',{timeZone:'Europe/London',day:'numeric',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}):'Unavailable';
export function researchOf(stock:Stock){return stock.research||composeResearch(effective(stock),{manualKeys:Object.keys(stock.manual)})}
export function CanslimBadge({stock}:{stock:Stock}){
 const r=researchOf(stock),c=r.canslim;
 if(c.notApplicable)return <span className="canslim-badge" title={c.verdict}><strong>N/A</strong><small>ETF</small></span>;
 return <span className="canslim-badge" title={`${c.passes} clear passes, ${c.partial} partial, ${c.fails} fails, ${c.unknown} unknown. Screening score, not an IBD rating.`}><strong>{c.passes}<span>/7</span></strong><small>{c.unknown?`${c.unknown} unverified`:'clear passes'}</small></span>;
}
export default function ResearchPanel({stock,onNotes,refresh,refreshing}:{stock:Stock;onNotes:()=>void;refresh:()=>void;refreshing:boolean}){
 const r=researchOf(stock),s=effective(stock),c=r.canslim,t=r.technicals;
 return <div className="research-panel">
  <div className="draft-topline"><span><BookOpen size={14}/>AUTOMATIC RESEARCH DRAFT</span><small>Updated {date(r.generatedAt)} UK</small></div>
  <div className="thesis-themes">{r.themes.map(theme=><span className="theme-tag" key={theme}>{theme}</span>)}</div>
  <h3 className="thesis-title">{r.title}</h3>
  <p className="thesis-summary">{r.summary}</p>
  <div className="style-fit"><span>YOUR INVESTMENT LENS</span><p>{r.styleFit}</p></div>
  <section className="thesis-section"><div className="section-title"><h3><TrendingUp size={16}/>Current price & trend</h3><span className={`trend-tag ${t.trend==='Uptrend'?'up':t.trend==='Downtrend'?'down':''}`}>{t.trend}</span></div><p className="thesis-asof"><Clock3 size={11}/>Quote as of {date(r.quoteAt)} UK</p>
    <div className="technical-grid"><div><span>20-day average</span><strong>{n(t.sma20)}</strong></div><div><span>50-day average</span><strong>{n(t.sma50)}</strong></div><div><span>200-day average</span><strong>{n(t.sma200)}</strong></div><div><span>1-month return</span><strong>{p(t.return1m)}</strong></div><div><span>3-month return</span><strong>{p(t.return3m)}</strong></div><div><span>Daily RSI (14)</span><strong>{t.rsi14?.toFixed(1)||'—'}</strong></div></div>
    {r.priceCommentary.map((paragraph,i)=><p className="thesis-prose" key={i}>{paragraph}</p>)}
  </section>
  <section className="thesis-section"><h3>The potential bull case</h3><ul className="thesis-points positive-points">{r.bullCase.map((item,i)=><li key={i}>{item}</li>)}</ul></section>
  <section className="thesis-section"><h3>The bear case & risks</h3><ul className="thesis-points risk-points">{r.bearCase.map((item,i)=><li key={i}>{item}</li>)}</ul></section>
  <section className="thesis-section"><h3>Catalysts & evidence to check</h3><ul className="thesis-points">{r.catalysts.map((item,i)=><li key={i}>{item}</li>)}</ul>
    {!!s.headlines?.length&&<div className="thesis-headlines"><span>HEADLINE LEADS · NOT VERIFIED DEVELOPMENTS</span>{s.headlines.map((h,i)=><a key={i} href={h.url} target="_blank" rel="noreferrer"><div>{h.title}<small>{h.date||'Publication date unavailable'}</small></div><ExternalLink size={13}/></a>)}</div>}
  </section>
  <section className="thesis-section canslim-section">{c.notApplicable?<><h3>CANSLIM · not applicable</h3><p className="canslim-verdict">{c.verdict}</p></>:<><div className="section-title"><h3>CANSLIM evidence score</h3><div className="canslim-score">{c.passes}<span>/7 clear passes</span></div></div>
    <div className="score-breakdown"><span className="pass">{c.passes} pass</span><span className="partial">{c.partial} partial</span><span className="fail">{c.fails} fail</span><span className="unknown">{c.unknown} unknown</span></div>
    <p className="canslim-verdict">{c.verdict}</p>
    <div className="canslim-criteria">{c.criteria.map(criterion=><details key={criterion.letter}><summary><span className="criterion-letter">{criterion.letter}</span><strong>{criterion.name}</strong><span className={`criterion-status ${criterion.status}`}>{criterion.status==='unknown'?'Unverified':criterion.status}</span><ChevronRight size={14}/></summary><p>{criterion.evidence}</p><div className="criterion-sources">{criterion.sourceKeys.map(key=>s.sources[key]&&<a key={key} href={s.sources[key].url} target="_blank" rel="noreferrer">{s.sources[key].name}<ExternalLink size={10}/></a>)}</div></details>)}</div>
    <p className="screen-note">A clear-pass count across seven factors. Partial and unknown evidence does not earn a pass. Leadership and market direction use disclosed proxies; this is not the proprietary IBD Composite or RS Rating.</p>
    <a className="text-button" href="https://www.investors.com/how-to-invest/" target="_blank" rel="noreferrer">CANSLIM / IBD investing resources <ArrowUpRight size={13}/></a>
  </>}</section>
  <section className="tigger-pending"><span className="pill neutral">Framework pending</span><h3>Tigger · The Trader’s Handbook</h3><p>The exact handbook edition and criteria have not been verified. A Tigger score will remain unassigned until the author or relevant page is identified.</p></section>
  <section className="thesis-section"><h3>What would change the view?</h3><ul className="thesis-points">{r.invalidation.map((item,i)=><li key={i}>{item}</li>)}</ul></section>
  <section className="thesis-section"><h3>Research sources</h3><div className="research-source-links">{Object.entries(s.sources).filter(([key])=>['quote','profile','stats','quarterly','annual','benchmark','news','fund'].includes(key)).map(([key,source])=><a key={key} href={source.url} target="_blank" rel="noreferrer"><span>{source.name}<small>{source.error?'Unavailable · previous dated values may be retained':`Fetched ${date(source.fetchedAt)} UK`}</small></span><ExternalLink size={13}/></a>)}{s.companyWebsite&&<a href={s.companyWebsite} target="_blank" rel="noreferrer"><span>{c.notApplicable?'Fund issuer':'Company website'}<small>Verify the latest disclosures and announcements</small></span><ExternalLink size={13}/></a>}</div></section>
  <details className="research-limitations"><summary>Scope, missing evidence & methodology</summary>{r.limitations.map((item,i)=><p key={i}>{item}</p>)}</details>
  <div className="research-actions"><button className="button primary" onClick={onNotes}><BookOpen size={14}/>Add your own notes</button><button className="button secondary" onClick={refresh} disabled={refreshing}><RefreshCw size={14} className={refreshing?'spin':''}/>Refresh research</button></div>
 </div>;
}
