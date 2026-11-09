"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ArrowDown, ArrowDownToLine, ArrowUpRight, BarChart3, BookOpen, Check, CheckCircle2, ChevronDown, ChevronRight, CircleHelp, Clock3, ExternalLink, FileText, Flame, LayoutGrid, ListFilter, LoaderCircle, LockKeyhole, Plus, RefreshCw, Search, Settings2, ShieldCheck, TrendingUp, Trash2, X } from "lucide-react";
import { effective, MANUAL_NUMBERS, squeezeChecks, STAGES, upside, type Snapshot, type Stock } from "../lib/model";

import ColumnHeader from "./column-header";
import ResearchPanel, {CanslimBadge,researchOf} from "./research-panel";

type View = "watchlist" | "squeeze" | "notes" | "sources";
const em = "—";
const number = (n: number | undefined | null, dp = 2) => n == null || !Number.isFinite(n) ? em : n.toLocaleString("en-GB", { maximumFractionDigits: dp, minimumFractionDigits: dp });
const compact = (n: number | undefined) => n == null ? em : new Intl.NumberFormat("en-GB", {notation:"compact", maximumFractionDigits:2}).format(n);
const money = (n: number | undefined | null, currency = "USD") => n == null ? em : `${n<0?"−":""}${currency === "USD" ? "$" : currency === "GBP" ? "£" : currency === "GBp" ? "p " : currency === "EUR" ? "€" : currency + " "}${number(Math.abs(n))}`;
const percent = (n: number | undefined | null, signed = false, dp = 1) => n == null ? em : `${signed && n > 0 ? "+" : ""}${number(n,dp)}%`;
function stamp(s?: string, full = false) {
  if (!s) return "Not available";
  const d = new Date(s); if (!Number.isFinite(d.getTime())) return s;
  return d.toLocaleString("en-GB", {timeZone:"Europe/London", day:"numeric", month:"short", ...(full ? {year:"numeric"} : {}), ...(/^\d{4}-\d\d-\d\d$/.test(s) ? {} : {hour:"2-digit",minute:"2-digit"})});
}
function Icon({children}: {children: ReactNode}) {return <span className="icon-wrap">{children}</span>}
function Mark({ticker,small=false}: {ticker:string;small?:boolean}) {
  const palette:Record<string,string> = {USAR:"sand", IBRX:"aqua", ALMU:"violet", NVO:"blue", UUUU:"mint", SMR:"rose"};
  const bundled=["USAR","IBRX","ALMU","NVO","UUUU","SMR"].includes(ticker);
  const symbol=encodeURIComponent(ticker.toLowerCase());
  const candidates=[...(bundled?[`/logos/${symbol}.svg`]:[]),`https://logos.stockanalysis.com/${symbol}.svg`,`https://logos.stockanalysis.com/${symbol}.png`];
  const [attempt,setAttempt]=useState(0),[loaded,setLoaded]=useState(false);
  useEffect(()=>{setAttempt(0);setLoaded(false)},[ticker]);
  return <span aria-hidden="true" className={`stock-mark ${palette[ticker] || "blue"} ${small ? "small" : ""} ${loaded?"has-company-logo":""}`}>
    {!loaded&&<span>{ticker.slice(0,2)}</span>}
    {candidates[attempt]&&<img className={`company-logo ${loaded?"is-loaded":""}`} src={candidates[attempt]} alt="" width={32} height={32} loading="lazy" decoding="async" referrerPolicy="no-referrer" onLoad={()=>setLoaded(true)} onError={()=>{setLoaded(false);setAttempt(n=>n+1)}}/>}
  </span>;
}
function Spark({values=[], large=false}: {values?:number[];large?:boolean}) {
  if(values.length < 2) return <span className="muted">{em}</span>;
  const w=large?540:90,h=large?150:30,pad=large?8:2;
  const min=Math.min(...values),max=Math.max(...values),range=max-min||1;
  const pts=values.map((v,i)=>`${pad+i/(values.length-1)*(w-pad*2)},${h-pad-(v-min)/range*(h-pad*2)}`).join(" ");
  const positive=values.at(-1)!>=values[0];
  return <svg viewBox={`0 0 ${w} ${h}`} className={`spark ${large?"large":""} ${positive?"positive":"negative"}`} role="img" aria-label={`Three-month daily closing prices, ${positive?"up":"down"} across this period`} preserveAspectRatio="none">
    {large && <><line x1="0" x2={w} y1={h/2} y2={h/2} stroke="#e9eef3" strokeDasharray="4 5"/><polygon points={`${pad},${h} ${pts} ${w-pad},${h}`} fill={positive?"#e8f4ef":"#f9eceb"}/></>}
    <polyline fill="none" stroke="currentColor" strokeWidth={large?2:1.7} points={pts} strokeLinejoin="round" strokeLinecap="round"/>
  </svg>;
}
function Gap({s}: {s:Snapshot}) {
  const u=upside(s); const label=u==null?"No target":u>=50?"Large target gap":u>=20?"Below target":u>=0?"Near target":"Above target";
  return <span className={`pill ${u==null?"neutral":u>=50?"green":u>=20?"blue":u>=0?"neutral":"amber"}`}><span className="pill-dot"/>{label}</span>;
}
function Freshness({stock}: {stock:Stock}) {
  const errors=Object.values(stock.snapshot.sources).filter(s=>s.error).length;
  return <span className={`freshness ${errors?"warn":""}`} title={errors?`${errors} source${errors>1?"s":""} unavailable; previous values may be retained. Open the stock for details.`:"Use refresh to fetch a new snapshot."}><span/>{errors?"Partial data":"Snapshot"}</span>;
}
function Modal({title,close,children,wide=false}: {title:string;close:()=>void;children:ReactNode;wide?:boolean}) {
  const ref=useRef<HTMLDivElement>(null), closeRef=useRef(close);closeRef.current=close;
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement, old=document.body.style.overflow;
    document.body.style.overflow="hidden";
    const timer=setTimeout(()=>{ref.current?.querySelector<HTMLElement>("input,button,select,textarea,a[href]")?.focus()},0);
    const key=(e:KeyboardEvent)=>{
      if(e.key==="Escape")closeRef.current();
      if(e.key==="Tab"){
        const els=Array.from(ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select,textarea,a[href],[tabindex="0"]')||[]).filter(e=>e.offsetParent!==null);
        const first=els[0],last=els.at(-1);if(!first)return;
        if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}
      }
    };document.addEventListener("keydown",key);
    return()=>{clearTimeout(timer);document.body.style.overflow=old;document.removeEventListener("keydown",key);previous?.focus()};
  },[]);
  return <div className={`overlay ${wide?"drawer-overlay":""}`} onMouseDown={e=>{if(e.target===e.currentTarget)close()}}><div ref={ref} className={wide?"drawer":"modal"} role="dialog" aria-modal="true" aria-label={title}><button className="icon-button modal-close" onClick={close} aria-label="Close dialog"><X size={20}/></button>{children}</div></div>;
}
async function request(body?:unknown): Promise<any> {
  const r=await fetch("/api/desk", body?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body),signal:AbortSignal.timeout(45000)}:{cache:"no-store",signal:AbortSignal.timeout(45000)});
  const data:any=await r.json();if(!r.ok)throw new Error(data.error||"The request failed.");return data;
}

export default function Desk() {
  const [stocks,setStocks]=useState<Stock[]>([]),[loading,setLoading]=useState(true),[loadError,setLoadError]=useState("");
  const [view,setView]=useState<View>("watchlist"),[query,setQuery]=useState(""),[sort,setSort]=useState("upside"),[filter,setFilter]=useState("All stocks");
  const [selected,setSelected]=useState<string|null>(null),[adding,setAdding]=useState(false),[ticker,setTicker]=useState(""),[addError,setAddError]=useState("");
  const [busy,setBusy]=useState<Set<string>>(new Set()),[allRefreshing,setAllRefreshing]=useState(false),[refreshProgress,setRefreshProgress]=useState("");
  const [toast,setToast]=useState<{text:string;error?:boolean}|null>(null);
  const notify=(text:string,error=false)=>setToast({text,error});
  async function load(){setLoading(true);setLoadError("");try{setStocks((await request()).stocks)}catch(e){setLoadError((e as Error).message)}finally{setLoading(false)}}
  useEffect(()=>{load()},[]);
  useEffect(()=>{if(!toast)return;const t=setTimeout(()=>setToast(null),6000);return()=>clearTimeout(t)},[toast]);
  function replace(s:Stock){setStocks(prev=>prev.some(p=>p.ticker===s.ticker)?prev.map(p=>p.ticker===s.ticker?s:p):[...prev,s])}
  async function action(body:any){const data=await request(body);if(data.stock)replace(data.stock);return data}
  async function refreshOne(stock:Stock,silent=false){
    setBusy(prev=>new Set(prev).add(stock.ticker));
    try{
      const data=await action({action:"refresh",ticker:stock.ticker});
      const failed=Object.values(data.stock.snapshot.sources).filter((s:any)=>s.error).length;
      if(!silent)notify(data.throttled?"Just refreshed. Wait 20 seconds before trying again.":failed?`${stock.ticker}: refresh completed with ${failed} unavailable source${failed>1?"s":""}. Dated values retained where available.`:`${stock.ticker} refreshed.`,!!failed);
      return {failed:!!failed};
    }catch(e){if(!silent)notify((e as Error).message,true);return {failed:true}}
    finally{setBusy(prev=>{const n=new Set(prev);n.delete(stock.ticker);return n})}
  }
  async function refreshAll(){
    if(allRefreshing||busy.size)return;
    setAllRefreshing(true);let failures=0;
    for(let i=0;i<stocks.length;i++){setRefreshProgress(`${i+1} of ${stocks.length} · ${stocks[i].ticker}`);if((await refreshOne(stocks[i],true)).failed)failures++}
    setAllRefreshing(false);setRefreshProgress("");notify(failures?`Refresh finished. ${failures} stock${failures>1?"s have":" has"} unavailable sources; check Data & sources.`:`All ${stocks.length} stocks refreshed.`,!!failures);
  }
  async function add(e:React.FormEvent){e.preventDefault();const t=ticker.trim().toUpperCase();if(!t)return;setAddError("");setBusy(prev=>new Set(prev).add("adding"));try{await action({action:"add",ticker:t});setAdding(false);setTicker("");setSelected(t);notify(`${t} added with its research draft.`)}catch(e){setAddError((e as Error).message)}finally{setBusy(prev=>{const n=new Set(prev);n.delete("adding");return n})}}
  function navigate(v:View){setView(v);setQuery("");setFilter("All stocks");setSort(v==="squeeze"?"pressure":"upside")}
  const selectedStock=stocks.find(s=>s.ticker===selected);
  const rows=useMemo(()=>stocks.filter(s=>`${s.ticker} ${s.name}`.toLowerCase().includes(query.toLowerCase())).filter(s=>filter==="All stocks"||s.stage===filter||(filter.startsWith("Theme: ")&&(researchOf(s).themes.includes(filter.slice(7))||(filter==="Theme: Robotics"&&researchOf(s).themes.includes("Robotics enabler"))))||(filter==="Large target gap"&&(upside(effective(s))??-Infinity)>=50)||(filter==="High short interest"&&(effective(s).shortFloatPct??0)>=20)).sort((a,b)=>{
    const aa=effective(a),bb=effective(b);
    if(sort==="ticker")return a.ticker.localeCompare(b.ticker);
    if(sort==="short")return (bb.shortFloatPct??-Infinity)-(aa.shortFloatPct??-Infinity);
    if(sort==="fee")return (bb.borrowFee??-Infinity)-(aa.borrowFee??-Infinity);
    if(sort==="pressure")return squeezeChecks(bb).filter(c=>c.passed).length-squeezeChecks(aa).filter(c=>c.passed).length;
    return (upside(bb)??-Infinity)-(upside(aa)??-Infinity);
  }),[stocks,query,filter,sort]);
  const withTargets=stocks.map(effective).filter(s=>upside(s)!=null),gaps=withTargets.filter(s=>(upside(s)??0)>=50).length;
  const highShort=stocks.filter(s=>(effective(s).shortFloatPct??0)>=20).length;
  const latest=stocks.map(s=>s.snapshot.attemptedAt).filter(Boolean).sort().at(-1);
  function exportCSV(){
    const headers=["Ticker","Company","Currency","Price","Quote as of","Average analyst target","Target upside %","EPS TTM","Forward PE","Short float %","Shares short","SI settlement date","Days to cover","Borrow fee % p.a.","Shares available IBKR","Borrow as of","Stage","Notes","Manual overrides","Draft thesis","Price trend","CANSLIM clear passes","CANSLIM unverified"];
    const csv=[headers,...stocks.map(st=>{const s=effective(st);return [st.ticker,st.name,s.currency,s.price,s.quoteAt,s.target,upside(s),s.eps,s.forwardPE,s.shortFloatPct,s.shortShares,s.shortDate,s.daysToCover,s.borrowFee,s.available,s.borrowAt,st.stage,st.notes,JSON.stringify(st.manual),researchOf(st).summary,researchOf(st).technicals.trend,researchOf(st).canslim.passes,researchOf(st).canslim.unknown]})].map(row=>row.map(c=>'"'+String(c??"").replace(/"/g,'""')+'"').join(",")).join("\r\n");
    const url=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8;"}));const a=document.createElement("a");a.href=url;a.download=`research-desk-${new Date().toISOString().slice(0,10)}.csv`;a.click();URL.revokeObjectURL(url);notify("Watchlist exported.");
  }
  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="Research Desk home"><span className="brand-mark"><BarChart3 size={23}/></span><span>research<span className="brand-light">desk</span><small>YOUR EDGE IS IN THE WORK</small></span></a>
      <div className="workspace-label">OLLIE’S WORKSPACE</div>
      <nav aria-label="Main navigation">
        {[{id:"watchlist",label:"Valuation watchlist",icon:LayoutGrid},{id:"squeeze",label:"Short squeeze",icon:Flame},{id:"notes",label:"Investment theses",icon:BookOpen},{id:"sources",label:"Data & sources",icon:Settings2}].map(n=><button key={n.id} aria-label={n.label} title={n.label} onClick={()=>navigate(n.id as View)} className={`nav-item ${view===n.id?"active":""}`}><n.icon size={18}/><span>{n.label}</span>{n.id==="watchlist"&&<small>{stocks.length}</small>}</button>)}
      </nav>
      <div className="sidebar-tip"><span className="tip-symbol"><TrendingUp size={20}/></span><strong>A target is a starting point.</strong><p>Find the valuation gap. Check the business. Review the thesis.</p><button onClick={()=>navigate("notes")}>Make it your own <ArrowUpRight size={14}/></button></div>
      <div className="sidebar-bottom"><div className="avatar">OB</div><div><strong>Ollie’s desk</strong><span><LockKeyhole size={11}/> Private workspace</span></div></div>
    </aside>
    <main className="main">
      <header className="topbar"><div className="breadcrumb">Workspace <ChevronRight size={13}/><span>{view==="watchlist"?"Valuation watchlist":view==="squeeze"?"Short squeeze":view==="notes"?"Investment theses":"Data & sources"}</span></div><div className="manual-mode"><span/>Manual refresh only <span className="top-divider"/><LockKeyhole size={13}/><span className="private-text">Private</span></div></header>
      <div className="content">
        <section className="page-heading"><div><div className="eyebrow"><span/>THE RESEARCH DESK</div><h1>{view==="watchlist"?"A clearer view of value.":view==="squeeze"?"Where the pressure builds.":view==="notes"?"The case behind the ticker.":"Know what’s behind the numbers."}</h1><p>{view==="watchlist"?"The stocks you’re watching. The numbers that matter. Your next piece of research.":view==="squeeze"?"Short interest, borrowing pressure and volume — side by side.":view==="notes"?"Automatically researched on addition. Built around your themes, valuation discipline and price confirmation.":"Dated snapshots, transparent sources and a refresh when you need one."}</p></div><div className="heading-actions"><button className="button secondary" onClick={refreshAll} disabled={loading||allRefreshing||!!busy.size||!stocks.length}><RefreshCw size={15} className={allRefreshing?"spin":""}/>{allRefreshing?refreshProgress:"Refresh all"}</button><button className="button primary" onClick={()=>{setAdding(true);setAddError("")}} disabled={loading||allRefreshing}><Plus size={17}/>Add ticker</button></div></section>
        {loadError?<div className="error-banner" role="alert">{loadError}<button onClick={load}>Try again</button></div>:<>
        <section className="summary-grid" aria-label="Watchlist overview">
          <div className="summary-card"><div className="summary-label">On your desk<LayoutGrid size={16}/></div><div className="summary-value">{loading?em:stocks.length}<span>stocks</span></div><div className="summary-caption">One place for your research</div></div>
          <div className="summary-card"><div className="summary-label">Large target gaps<TrendingUp size={17}/></div><div className="summary-value green-text">{loading?em:gaps}<span>opportunities to research</span></div><div className="summary-caption">≥ 50% to the average analyst target</div></div>
          <div className="summary-card"><div className="summary-label">Elevated short interest<Flame size={17}/></div><div className="summary-value">{loading?em:highShort}<span>on squeeze watch</span></div><div className="summary-caption">Reported short interest ≥ 20% of float</div></div>
          <div className="summary-card last-refresh"><div className="summary-label">Last refresh attempt<Clock3 size={16}/></div><div className="refresh-value">{loading?em:latest?stamp(latest):"Not yet refreshed"}</div><div className="summary-caption">{allRefreshing?<><span className="small-spinner"/>Fetching new snapshots…</>:"Source timestamps shown per stock · UK time"}</div></div>
        </section>
        {(view==="watchlist"||view==="squeeze")&&<>
          <section className="desk-panel">
            <div className="panel-heading"><div><h2>{view==="watchlist"?"The watchlist":"The squeeze watch"}<span className="count-badge">{stocks.length}</span></h2><p>{view==="watchlist"?"Start with the gap. Open a stock to go deeper.":"A research checklist, not a squeeze prediction."}</p></div><button className="text-button export-button" onClick={exportCSV} disabled={!stocks.length}><ArrowDownToLine size={14}/>Export CSV</button></div>
            <div className="table-toolbar"><div className="segmented"><button className={view==="watchlist"?"selected":""} onClick={()=>navigate("watchlist")}><BarChart3 size={14}/>Valuation</button><button className={view==="squeeze"?"selected":""} onClick={()=>navigate("squeeze")}><Flame size={14}/>Short squeeze</button></div><div className="table-controls"><label className="search-box"><Search size={15}/><input placeholder="Find a stock…" aria-label="Search watchlist" value={query} onChange={e=>setQuery(e.target.value)}/></label><label className="select-wrap filter-select"><ListFilter size={14}/><select aria-label="Filter stocks" value={filter} onChange={e=>setFilter(e.target.value)}>{["All stocks","Large target gap","High short interest","Theme: Nuclear","Theme: Metal mining","Theme: Robotics","Theme: Medical",...STAGES].map(o=><option key={o}>{o}</option>)}</select></label><label className="select-wrap sort-select"><ArrowDown size={13}/><select aria-label="Sort stocks" value={sort} onChange={e=>setSort(e.target.value)}><option value="upside">Target upside</option><option value="ticker">Ticker A–Z</option><option value="short">Short interest</option><option value="fee">Borrow fee</option><option value="pressure">Pressure checks</option></select></label></div></div>
            <div className="table-scroll"><table className={`stock-table ${view==="squeeze"?"squeeze-table":""}`}><thead><tr>
              <ColumnHeader topic="company" className="company-col">COMPANY</ColumnHeader>
              <ColumnHeader topic="price">PRICE</ColumnHeader>
              {view==="watchlist"?<>
                <ColumnHeader topic="trend">3M TREND</ColumnHeader>
                <ColumnHeader topic="target">AVG. TARGET</ColumnHeader>
                <ColumnHeader topic="upside">UPSIDE <ArrowDown size={10}/></ColumnHeader>
                <ColumnHeader topic="eps">EPS <small>TTM</small></ColumnHeader>
                <ColumnHeader topic="pe">FWD P/E</ColumnHeader>
                <ColumnHeader topic="canslim">CANSLIM</ColumnHeader>
                <ColumnHeader topic="gap">TARGET GAP</ColumnHeader>
              </>:<>
                <ColumnHeader topic="short">SHORT FLOAT</ColumnHeader>
                <ColumnHeader topic="cover">DAYS TO COVER</ColumnHeader>
                <ColumnHeader topic="fee">BORROW FEE</ColumnHeader>
                <ColumnHeader topic="available">AVAILABLE <small>IBKR</small></ColumnHeader>
                <ColumnHeader topic="volume">DAY VOL / AVG</ColumnHeader>
                <ColumnHeader topic="checklist">CHECKLIST</ColumnHeader>
              </>}
              <ColumnHeader topic="data">DATA</ColumnHeader>
              <ColumnHeader topic="actions">ACTIONS</ColumnHeader>
            </tr></thead><tbody>
              {loading?Array.from({length:6},(_,i)=><tr key={i} className="skeleton-row"><td colSpan={view==="watchlist"?11:10}><div/></td></tr>):rows.map(stock=>{
                const s=effective(stock),u=upside(s),checks=squeezeChecks(s),passed=checks.filter(c=>c.passed).length;
                return <tr key={stock.ticker} className={busy.has(stock.ticker)?"row-busy":""}>
                  <td className="company-cell"><button className="company-button" onClick={()=>setSelected(stock.ticker)}><Mark ticker={stock.ticker}/><span><strong>{stock.ticker}{Object.keys(stock.manual).length>0&&<span className="manual-star" title="Contains manual overrides">*</span>}</strong><span className="company-name">{stock.name}</span></span></button></td>
                  <td><strong className="data-price">{money(s.price,s.currency)}</strong><small className={`sub-value ${(s.changePct??0)>=0?"green-text":"red-text"}`}>{percent(s.changePct,true)}</small></td>
                  {view==="watchlist"?<><td><Spark values={s.closes}/></td><td><strong className="regular-number">{money(s.target,s.currency)}</strong><small className="sub-value">{s.analystCount!=null?`${s.analystCount} analysts`:"Coverage unavailable"}</small></td><td><strong className={`upside-value ${(u??0)>=0?"green-text":"red-text"}`}>{percent(u,true)}</strong></td><td><span className={(s.eps??0)<0?"soft-red":""}>{money(s.eps,s.currency)}</span></td><td>{s.forwardPE!=null?`${number(s.forwardPE,1)}×`:<><span className="muted">N/A</span><small className="sub-value">Not published</small></>}</td><td><CanslimBadge stock={stock}/></td><td><Gap s={s}/></td></>:<><td><strong className={(s.shortFloatPct??0)>=20?"amber-text":""}>{percent(s.shortFloatPct)}</strong><small className="sub-value">{s.shortDate?stamp(s.shortDate):"Date unverified"}</small></td><td>{number(s.daysToCover,2)}<small className="sub-value">days</small></td><td><strong className={(s.borrowFee??0)>=10?"amber-text":""}>{percent(s.borrowFee,false,2)}</strong><small className="sub-value">annualised</small></td><td>{compact(s.available)}<small className="sub-value">{s.borrowAt?stamp(s.borrowAt):"Not published"}</small></td><td>{s.relativeVolume!=null?`${number(s.relativeVolume,2)}×`:em}</td><td><div className="checks-meter" aria-label={`${passed} of 5 conditions met, ${checks.filter(c=>!c.known).length} unknown`}>{checks.map((c,i)=><span key={i} title={`${c.label}: ${c.known?(c.passed?"met":"not met"):"unavailable"}`} className={c.known?(c.passed?"met":"unmet"):"unknown"}/>)}</div><small className="sub-value">{passed}/5 met{checks.some(c=>!c.known)?` · ${checks.filter(c=>!c.known).length} unknown`:""}</small></td></>}
                  <td><Freshness stock={stock}/><small className="sub-value">{s.quoteAt?stamp(s.quoteAt):"No quote time"}</small></td><td className="row-actions"><button className="icon-button" aria-label={`Refresh ${stock.ticker}`} title={`Refresh ${stock.ticker}`} disabled={allRefreshing||busy.has(stock.ticker)} onClick={()=>refreshOne(stock)}><RefreshCw size={14} className={busy.has(stock.ticker)?"spin":""}/></button><button className="icon-button open-stock" aria-label={`Open ${stock.ticker} research`} onClick={()=>setSelected(stock.ticker)}><ChevronRight size={17}/></button></td>
                </tr>;
              })}
            </tbody></table>{!loading&&!rows.length&&<div className="empty-state"><Search size={24}/><h3>{stocks.length?"No stocks match that search":"Your desk is ready"}</h3><p>{stocks.length?"Try another ticker or clear the filters.":"Add your first ticker to begin researching."}</p><button className="button secondary" onClick={()=>stocks.length?(setQuery(""),setFilter("All stocks")):setAdding(true)}>{stocks.length?"Clear filters":"Add a ticker"}</button></div>}</div>
            <div className="table-footer"><span><span className="status-dot"/>{rows.length} of {stocks.length} stocks<span className="footer-divider">·</span>{view==="watchlist"?"Analyst targets are estimates, not fair value.":"Reported short interest is periodic. Borrowing data is one broker’s snapshot."}</span><span>Click a company to explore <ArrowUpRight size={12}/></span></div>
          </section>
          <section className="bottom-grid"><div className="research-card"><div className="card-topline"><span className="mini-icon"><BookOpen size={17}/></span><span>YOUR RESEARCH PROCESS</span></div><h3>The gap gets your attention.<br/>The thesis earns your conviction.</h3><p>Check profitability, upcoming catalysts and dilution. Use your notes to record what would change your mind.</p><button className="text-button" onClick={()=>navigate("notes")}>Open research notes <ArrowUpRight size={14}/></button></div><div className="radar-card"><div className="radar-heading"><h3><Flame size={17}/>Pressure on the radar</h3><button className="text-button" onClick={()=>navigate("squeeze")}>View all <ArrowUpRight size={13}/></button></div>{stocks.length?stocks.slice().sort((a,b)=>(effective(b).shortFloatPct??-1)-(effective(a).shortFloatPct??-1)).slice(0,3).map(stock=>{const s=effective(stock);return <button className="radar-row" key={stock.ticker} onClick={()=>setSelected(stock.ticker)}><Mark ticker={stock.ticker} small/><span className="radar-ticker">{stock.ticker}<small>{s.shortDate?`SI · ${stamp(s.shortDate)}`:"SI date unverified"}</small></span><span className="radar-metric"><strong>{percent(s.shortFloatPct)}</strong><small>short float</small></span><span className="radar-metric"><strong>{percent(s.borrowFee,false,2)}</strong><small>borrow fee</small></span><ChevronRight size={15}/></button>}):<p className="muted">Add stocks to see their reported short interest.</p>}<p className="radar-note">High short interest alone doesn’t create a squeeze.</p></div></section>
        </>}
        {view==="notes"&&<section className="notes-grid">{stocks.map(stock=><button className="note-card" key={stock.ticker} onClick={()=>setSelected(stock.ticker)}><div className="note-heading"><Mark ticker={stock.ticker}/><div><strong>{stock.ticker}</strong><span>{stock.name}</span></div><ArrowUpRight size={17}/></div><span className="pill neutral">{stock.stage}</span><div className="note-research-tags">{researchOf(stock).themes.map(theme=><span className="theme-tag" key={theme}>{theme}</span>)}<CanslimBadge stock={stock}/></div><h3 className="note-thesis-title">{researchOf(stock).title.split(": ").slice(1).join(": ")}</h3><p className="note-preview">{researchOf(stock).summary}</p><span className="note-edit">Read the thesis · {researchOf(stock).technicals.trend}<ChevronRight size={14}/></span></button>)}{!stocks.length&&!loading&&<div className="empty-state"><BookOpen/><h3>Your research starts with a ticker.</h3><button className="button primary" onClick={()=>setAdding(true)}>Add ticker</button></div>}</section>}
        {view==="sources"&&<Sources stocks={stocks} open={setSelected}/>}
        </>}
        <footer className="page-footer"><span><ShieldCheck size={13}/>Your private research workspace</span><span>Research on addition · refresh on demand · all times UK.</span></footer>
      </div>
    </main>
    {toast&&<div className={`toast ${toast.error?"toast-error":""}`} role="status">{toast.error?<CircleHelp size={18}/>:<CheckCircle2 size={18}/>}<span>{toast.text}</span><button onClick={()=>setToast(null)} aria-label="Dismiss notification"><X size={15}/></button></div>}
    {adding&&<Modal title="Add a ticker" close={()=>{if(!busy.has("adding"))setAdding(false)}}><div className="modal-icon"><Plus size={23}/></div><div className="eyebrow">EXPAND YOUR RESEARCH</div><h2>Add to your desk.</h2><p className="modal-description">Enter a Yahoo Finance ticker. We’ll check the company, prices, financials and squeeze data, then write a tailored thesis and CANSLIM assessment automatically.</p><form onSubmit={add}><label className="field-label" htmlFor="new-ticker">Stock ticker</label><input id="new-ticker" className="input ticker-input" autoComplete="off" autoCapitalize="characters" placeholder="e.g. USAR" maxLength={15} value={ticker} onChange={e=>setTicker(e.target.value.toUpperCase())} disabled={busy.has("adding")} required/><p className="field-hint">US stocks have the widest valuation and borrowing coverage.</p>{addError&&<p className="form-error" role="alert">{addError}</p>}<button className="button primary full-width" disabled={busy.has("adding")||!ticker.trim()}>{busy.has("adding")?<><LoaderCircle className="spin" size={17}/>Researching company…</>:<><Plus size={17}/>Add ticker</>}</button></form></Modal>}
    {selectedStock&&<Detail key={selectedStock.ticker} stock={selectedStock} close={()=>setSelected(null)} save={action} refresh={()=>refreshOne(selectedStock)} refreshing={allRefreshing||busy.has(selectedStock.ticker)} notify={notify} remove={()=>{setStocks(prev=>prev.filter(s=>s.ticker!==selectedStock.ticker));setSelected(null)}}/>}
  </div>;
}

function Sources({stocks,open}: {stocks:Stock[];open:(t:string)=>void}) {
  return <div className="sources-page"><div className="source-guide-grid">
    <article className="source-guide"><div className="mini-icon"><BarChart3 size={20}/></div><h3>Prices & charts</h3><strong>Yahoo Finance</strong><p>Regular-session quote, a three-month chart and up to one year of daily history for trend research. The quote’s trade timestamp is shown separately from the time you clicked refresh.</p></article>
    <article className="source-guide"><div className="mini-icon"><TrendingUp size={20}/></div><h3>Valuation & short interest</h3><strong>Stock Analysis</strong><p>Average 12-month analyst target, target range, EPS TTM, forward P/E, float and short interest. EPS and forward P/E may be unavailable for unprofitable companies. Consensus can differ from Yahoo.</p></article>
    <article className="source-guide"><div className="mini-icon"><Flame size={20}/></div><h3>Borrowing & SI dates</h3><strong>ChartExchange / IBKR</strong><p>Annualised borrow fee and shares available at Interactive Brokers, not the entire market. A reported SI settlement date is attached only when the share count matches Stock Analysis.</p></article>
  </div><div className="source-explainer"><CircleHelp size={19}/><div><strong>Refresh checks each feed independently.</strong><p>If a feed fails, previous values keep their original dates and the failure appears below. Missing values stay blank. Manual overrides remain in place until cleared. Theses are drafted automatically when a stock is added and updated when you manually refresh. Your own notes are preserved.</p></div></div>
    <section className="desk-panel sources-list"><div className="panel-heading"><div><h2>Source health</h2><p>Open a stock for source links, timestamps and manual corrections.</p></div></div>{stocks.map(stock=><button className="source-stock" key={stock.ticker} onClick={()=>open(stock.ticker)}><strong>{stock.ticker}</strong><div>{Object.entries(stock.snapshot.sources).map(([key,s])=><span className={`source-chip ${s.error?"error":""}`} key={key} title={`${s.name}: ${s.error||`fetched ${stamp(s.fetchedAt,true)}`}`}><span/>{key==="quote"?"Quote":key==="stats"?"Statistics":key==="forecast"?"Targets":key==="borrow"?"Borrow":key==="short"?"SI date":key==="profile"?"Profile":key==="quarterly"?"Quarterly":key==="annual"?"Annual":key==="benchmark"?"Market":"Headlines"}{s.error?" · unavailable":""}</span>)}</div><ChevronRight size={16}/></button>)}</section>
    <article className="method-card"><h3>How to read the desk</h3><div className="method-grid"><div><strong>Target upside</strong><p>(Average analyst target ÷ price − 1) × 100. “Large target gap” means at least 50%; it does not establish undervaluation.</p></div><div><strong>Squeeze checklist</strong><p>Short float ≥ 20%, days to cover ≥ 3, borrow fee ≥ 10%, available shares ≤ 100k, and day volume / 20-day average ≥ 1.5×. The count is a heuristic, not a probability or buy signal.</p></div><div><strong>Volume & reporting dates</strong><p>Day volume / average volume is not adjusted for time of day. Intraday values are incomplete. Short interest is periodic; it is not short-sale volume.</p></div><div><strong>Target changes</strong><p>Target history starts when this desk records it. Changes are measured against saved snapshots, not an invented one-year history. Float definitions can differ by provider.</p></div></div></article>
  </div>;
}

function Detail({stock,close,save,refresh,refreshing,notify,remove}: {stock:Stock;close:()=>void;save:(b:any)=>Promise<any>;refresh:()=>void;refreshing:boolean;notify:(s:string,error?:boolean)=>void;remove:()=>void}) {
  const [tab,setTab]=useState("research"),[notes,setNotes]=useState(stock.notes),[stage,setStage]=useState(stock.stage),[saving,setSaving]=useState(false),[confirmDelete,setConfirmDelete]=useState(false);
  const s=effective(stock),u=upside(s),checks=squeezeChecks(s);
  const dirty=notes!==stock.notes||stage!==stock.stage;
  const safeClose=()=>{if(dirty){if(!window.confirm("You have unsaved research notes. Close without saving?"))return}close()};
  async function saveNotes(){setSaving(true);try{await save({action:"edit",ticker:stock.ticker,notes,stage});notify("Research notes saved.")}catch(e){notify((e as Error).message,true)}finally{setSaving(false)}}
  async function deleteStock(){setSaving(true);try{await save({action:"delete",ticker:stock.ticker});remove();notify(`${stock.ticker} removed from your desk.`)}catch(e){notify((e as Error).message,true);setSaving(false)}}
  return <Modal title={`${stock.ticker} research`} close={safeClose} wide>
    <div className="detail-header"><Mark ticker={stock.ticker}/><div><div className="detail-ticker">{stock.ticker}<span>{s.exchange||"Stock"} · {s.currency||"Currency unavailable"}</span></div><h2>{stock.name}</h2></div></div>
    <div className="detail-price"><div><strong>{money(s.price,s.currency)}</strong><span className={(s.changePct??0)>=0?"green-text":"red-text"}>{percent(s.changePct,true)} <small>regular session</small></span></div><button className="button secondary compact-button" disabled={refreshing} onClick={refresh}><RefreshCw size={14} className={refreshing?"spin":""}/>{refreshing?"Refreshing":"Refresh"}</button></div>
    <div className="quote-line">Quote as of {stamp(s.quoteAt,true)} UK · Public feed may be delayed{stock.manual.price&&" · Manual price"}</div>
    <div className="detail-tabs">{["research","overview","squeeze","notes","data"].map(t=><button key={t} className={tab===t?"active":""} onClick={()=>setTab(t)}>{t==="research"?"Thesis":t==="overview"?"Overview":t==="squeeze"?"Short squeeze":t==="notes"?"My notes":"Data & edits"}{t==="notes"&&stock.notes&&<span/>}</button>)}</div>
    <div className="detail-body">
      {tab==="research"&&<ResearchPanel stock={stock} onNotes={()=>setTab("notes")} refresh={refresh} refreshing={refreshing}/>}
      {tab==="overview"&&<>
        <div className="chart-header"><strong>Price history</strong><span>3 months · daily close</span></div><div className="detail-chart"><Spark values={s.closes} large/></div>{s.closeDates?.length&&<div className="chart-labels"><span>{stamp(s.closeDates[0])}</span><span>{stamp(s.closeDates.at(-1))}</span></div>}
        <section className="target-card"><div className="target-card-top"><span>AVERAGE ANALYST TARGET</span><Gap s={s}/></div><div className="target-card-value">{money(s.target,s.currency)}<span className={(u??0)>=0?"green-text":"red-text"}>{percent(u,true)} potential upside</span></div><div className="target-range"><span>Low <strong>{money(s.targetLow,s.currency)}</strong></span><span>Median <strong>{money(s.targetMedian,s.currency)}</strong></span><span>High <strong>{money(s.targetHigh,s.currency)}</strong></span></div><p>{s.analystCount!=null?`${s.analystCount} analysts · `:""}{s.consensus||"Consensus unavailable"} · Approx. 12-month targets. Estimates are not fair value.</p></section>
        <div className="detail-stats"><Fact label="EPS (TTM)" value={money(s.eps,s.currency)} extra={(s.eps??0)<0?"Loss-making over the trailing period":undefined}/><Fact label="Forward P/E" value={s.forwardPE!=null?`${number(s.forwardPE,1)}×`:em}/><Fact label="Market cap" value={compact(s.marketCap)}/><Fact label="EPS growth forecast (3Y)" value={percent(s.epsGrowth)}/><Fact label="52-week high" value={money(s.high52,s.currency)} extra={s.price&&s.high52?`${percent((s.price/s.high52-1)*100,true)} from high`:undefined}/><Fact label="52-week low" value={money(s.low52,s.currency)}/><Fact label="Next earnings (provider estimate)" value={s.earningsDate&&s.earningsDate!=="n/a"?s.earningsDate:em}/><Fact label="Shares outstanding" value={compact(s.sharesOutstanding)}/></div>
        <div className="detail-section"><h3>Target changes on your desk</h3>{stock.history.length>1?<div className="history-list">{stock.history.slice().reverse().slice(0,8).map((h,i)=><div key={i}><span>{stamp(h.recordedAt,true)}</span><strong>{money(h.target,s.currency)}</strong></div>)}</div>:<p className="muted">History starts with your saved snapshots. Refresh over time to track changes to the average target.</p>}</div>
        <button className="button secondary full-width" onClick={()=>setTab("notes")}><FileText size={16}/>{stock.notes?"Open your notes":"Add your own notes"}<ArrowUpRight size={15}/></button>
      </>}
      {tab==="squeeze"&&<>
        <div className="squeeze-summary"><span className="mini-icon"><Flame size={24}/></span><div><span className="eyebrow">PRESSURE CHECKLIST</span><h3>{checks.filter(c=>c.passed).length} of 5 conditions present</h3><p>{checks.filter(c=>!c.known).length} unknown · A research heuristic, not a prediction.</p></div></div>
        <div className="checklist">{checks.map(c=><div key={c.label}><span className={`check-icon ${c.passed?"passed":""}`}>{c.passed?<Check size={14}/>:c.known?<span className="empty-check"/>:"?"}</span><span>{c.label}</span><strong>{c.known?(c.passed?"Present":"Not met"):"No data"}</strong></div>)}</div>
        <div className="detail-section"><div className="section-title"><h3>Reported short interest</h3><span className="pill neutral">{s.shortDate?stamp(s.shortDate):"Date unverified"}</span></div><div className="detail-stats"><Fact label="Short interest / float" value={percent(s.shortFloatPct)}/><Fact label="Shares sold short" value={compact(s.shortShares)}/><Fact label="Days to cover" value={number(s.daysToCover,2)}/><Fact label="Previous reported shares short" value={compact(s.shortPrevious)} extra={s.shortPreviousDate?stamp(s.shortPreviousDate):"Previous period from provider"}/><Fact label="Reported SI change" value={percent(s.shortChangePct,true)}/><Fact label="Float (Stock Analysis)" value={compact(s.float)}/></div>{s.floatDisagreement&&<div className="inline-note"><CircleHelp size={17}/><p>Float estimates differ between providers. The short-float percentage and days to cover shown here use Stock Analysis. The settlement date is matched by the reported share count.</p></div>}<p className="field-hint">Short interest is published periodically, not in real time. Reporting date and fetch time are different.</p></div>
        <div className="detail-section"><h3>Borrowing pressure <span className="plain-badge">IBKR snapshot</span></h3><div className="detail-stats"><Fact label="Borrow fee (annualised)" value={percent(s.borrowFee,false,2)}/><Fact label="Shares available to borrow" value={s.available==null?em:number(s.available,0)}/><Fact label="Borrow snapshot as of" value={stamp(s.borrowAt,true)} extra={s.borrowAt&&Date.now()-Date.parse(s.borrowAt)>86400000?"Older than 24 hours":undefined}/><Fact label="Day volume / 20-day average" value={s.relativeVolume!=null?`${number(s.relativeVolume,2)}×`:em} extra="Not adjusted for time of day"/></div><p className="field-hint">Availability represents one broker’s inventory. A missing update is not treated as zero shares available.</p></div>
        <div className="inline-note"><CircleHelp size={18}/><p>Pressure needs a catalyst and a price response. Check dilution, filings and liquidity before treating crowded shorts as an opportunity.</p></div>
      </>}
      {tab==="notes"&&<><div className="detail-section notes-intro"><div className="eyebrow">YOUR RESEARCH, YOUR CALL</div><h3>What’s the case for {stock.ticker}?</h3><p className="muted">Your own notes stay separate from the automatically updated thesis.</p></div><label className="field-label" htmlFor="research-stage">Research stage</label><div className="form-select"><select id="research-stage" value={stage} onChange={e=>setStage(e.target.value)}>{STAGES.map(s=><option key={s}>{s}</option>)}</select><ChevronDown size={15}/></div><label className="field-label" htmlFor="research-notes">Your notes & decisions</label><textarea className="input notes-textarea" id="research-notes" value={notes} onChange={e=>setNotes(e.target.value)} maxLength={12000} placeholder={"Why might it be undervalued?\n\nWhat’s the catalyst?\n\nWhat are the risks — cash burn, dilution, debt?\n\nWhat would change my mind?\n\nMy entry area / invalidation / review date"}/><div className="notes-save"><span>{notes.length.toLocaleString()} / 12,000 {dirty?"· Unsaved changes":"· Saved"}</span><button className="button primary" onClick={saveNotes} disabled={saving||!dirty}>{saving?<LoaderCircle className="spin" size={15}/>:<Check size={15}/>}Save research</button></div></>}
      {tab==="data"&&<>
        <div className="detail-section"><h3>Feed status & timestamps</h3><p className="muted">Last refresh attempt: {stamp(stock.snapshot.attemptedAt,true)} UK</p><div className="source-details">{Object.entries(stock.snapshot.sources).map(([key,source])=><article className="source-detail" key={key}><div><a href={key==="quote"?`https://finance.yahoo.com/quote/${encodeURIComponent(stock.ticker)}/`:source.url} target="_blank" rel="noreferrer">{source.name}<ExternalLink size={12}/></a><span className={`pill ${source.error?"amber":"green"}`}>{source.error?"Unavailable":"Retrieved"}</span></div><p>Last successful fetch: {stamp(source.fetchedAt,true)} UK{source.asOf&&<><br/>Data as of: {stamp(source.asOf,true)} UK</>}</p>{source.error&&<p className="source-error">{source.error}. Previous dated values are kept where available.</p>}</article>)}</div></div>
        <ManualEditor stock={stock} save={save} notify={notify}/>
        <div className="delete-section">{confirmDelete?<div><p>Remove {stock.ticker} and its saved notes from this desk?</p><button className="button danger" onClick={deleteStock} disabled={saving}>Remove stock</button><button className="text-button" onClick={()=>setConfirmDelete(false)}>Keep it</button></div>:<button className="text-button danger-text" onClick={()=>setConfirmDelete(true)}><Trash2 size={15}/>Remove from watchlist</button>}</div>
      </>}
    </div>
  </Modal>;
}
function Fact({label,value,extra}: {label:string;value:string;extra?:string}) {return <div className="fact"><span>{label}</span><strong>{value}</strong>{extra&&<small>{extra}</small>}</div>}
const manualLabels:Record<string,string>={price:"Share price",target:"Average analyst target",eps:"EPS (TTM)",forwardPE:"Forward P/E",shortFloatPct:"Short float %",shortShares:"Shares short",daysToCover:"Days to cover",borrowFee:"Borrow fee % p.a.",available:"Shares available (IBKR)",shortDate:"SI settlement date"};
function ManualEditor({stock,save,notify}: {stock:Stock;save:(b:any)=>Promise<any>;notify:(s:string,e?:boolean)=>void}) {
  const [values,setValues]=useState<Record<string,string>>(()=>Object.fromEntries(Object.entries(stock.manual).map(([k,v])=>[k,String(v.value)])));
  const [source,setSource]=useState(Object.values(stock.manual)[0]?.source||"");
  const firstDate=Object.values(stock.manual)[0]?.asOf;
  const localDate=(iso?:string)=>{const d=iso?new Date(iso):new Date();return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16)};
  const [asOf,setAsOf]=useState(localDate(firstDate)),[saving,setSaving]=useState(false),[error,setError]=useState("");
  async function submit(e:React.FormEvent){e.preventDefault();setSaving(true);setError("");try{await save({action:"manual",ticker:stock.ticker,values,source,asOf:new Date(asOf).toISOString()});notify("Manual overrides saved. They stay in place until cleared.")}catch(e){setError((e as Error).message)}finally{setSaving(false)}}
  async function clear(){setSaving(true);try{await save({action:"manual",ticker:stock.ticker,values:{}});setValues({});setSource("");notify("Manual overrides cleared. Feed values are shown again.")}catch(e){notify((e as Error).message,true)}finally{setSaving(false)}}
  return <section className="manual-editor"><div className="section-title"><h3>Manual corrections</h3><span className="pill neutral">{Object.keys(stock.manual).length} overrides</span></div><p className="muted">Fill only the fields you want to override. Add a source and observation time. Refreshing keeps your corrections; clear them to return to feed values.</p>{Object.keys(stock.manual).length>0&&<div className="manual-provenance">Current overrides: {Object.entries(stock.manual).map(([key,v])=><p key={key}><strong>{manualLabels[key]||key}: {v.value}</strong><span>{v.source} · {stamp(v.asOf,true)} UK</span></p>)}</div>}<form onSubmit={submit}><div className="manual-fields">{[...MANUAL_NUMBERS,"shortDate"].map(key=><label key={key}>{manualLabels[key]}<input className="input" type={key==="shortDate"?"date":"number"} step={key==="shortDate"?undefined:"any"} placeholder={key==="shortDate"?undefined:"Use feed value"} value={values[key]||""} onChange={e=>setValues({...values,[key]:e.target.value})}/></label>)}</div><label className="field-label" htmlFor="manual-source">Source / reference URL</label><input className="input" id="manual-source" placeholder="e.g. IBKR snapshot or a source link" value={source} onChange={e=>setSource(e.target.value)} maxLength={500}/><label className="field-label" htmlFor="manual-time">Observed at (your browser’s local time)</label><input className="input" id="manual-time" type="datetime-local" value={asOf} onChange={e=>setAsOf(e.target.value)} required/>{error&&<p className="form-error" role="alert">{error}</p>}<div className="manual-actions"><button className="button primary" disabled={saving}>{saving?<LoaderCircle className="spin" size={15}/>:<Check size={15}/>}Save corrections</button><button type="button" className="text-button" onClick={clear} disabled={saving||!Object.keys(stock.manual).length}>Clear all overrides</button></div></form></section>;
}
