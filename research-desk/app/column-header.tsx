"use client";

import {useEffect,useId,useLayoutEffect,useRef,useState,type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {CircleHelp} from 'lucide-react';

const help = {
  company:{title:'Company & ticker',what:'The ticker is the company’s short stock-market code — for example, USAR.',why:'Click the company to open its thesis, financial details and your notes.'},
  price:{title:'Current share price',what:'The latest available regular-session price for one share. The percentage underneath is its daily change.',why:'Check the timestamp: a saved or delayed quote may differ from the price you could trade at now.'},
  trend:{title:'Three-month price trend',what:'A small chart of daily closing prices over roughly three months.',why:'It helps you see whether the stock has been rising, falling or moving sideways. It does not predict the next move.'},
  target:{title:'Average analyst target',what:'The average price analysts estimate the stock could reach in about 12 months.',why:'Compare it with today’s price to see their expected upside. Targets can be wrong or revised down.'},
  upside:{title:'Upside to the analyst target',what:'How much the price would need to rise to reach the average analyst target.',why:'For example, a $10 stock with a $15 target has 50% upside. A big gap is a research lead, not a guaranteed return.'},
  eps:{title:'EPS · earnings per share',what:'The company’s profit divided across its shares. TTM means “trailing twelve months” — the last year.',why:'Positive EPS means it made a profit; negative EPS means it made a loss. Growing EPS can support a higher share price.',example:'Example: EPS of $2 means about $2 of annual profit per share. It is not a dividend payment.'},
  pe:{title:'Forward P/E · price to earnings',what:'The share price divided by the profit per share analysts expect for the next year.',why:'At 20×, you are paying $20 for each $1 of forecast annual earnings. Compare similar businesses; a low ratio can also reflect weak growth or risk.',example:'N/A means the feed does not publish a usable ratio. This often happens when forecast earnings are negative or unavailable.'},
  canslim:{title:'CANSLIM · seven growth-stock checks',what:'Checks earnings growth, new developments, supply and demand, leadership, institutional backing and the market trend.',why:'The score counts clear passes out of seven. Partial, failed and unknown checks stay separate. Open the thesis to see the evidence.'},
  gap:{title:'Gap to the analyst target',what:'A quick label comparing today’s price with the average analyst target. “Large target gap” means at least 50% upside to that target.',why:'It helps you prioritise research. An optimistic analyst target alone does not prove the stock is undervalued.'},
  data:{title:'Data status & quote time',what:'“Snapshot” means the feeds were retrieved. “Partial data” means at least one feed was unavailable; older dated values may remain.',why:'The time underneath belongs to the price quote. Open Data & edits for each source’s own dates and any errors.'},
  short:{title:'Short float · shares bet against',what:'The percentage of publicly tradable shares reported as sold short — borrowed and sold by traders hoping the price falls.',why:'A high figure can create buying pressure if shorts rush to close, but it can also reflect serious business risks. The date is the reporting period.'},
  cover:{title:'Days to cover',what:'Reported shares sold short divided by average daily trading volume.',why:'It estimates how many normal-volume trading days buying back all those shares would represent. A higher number can make covering harder; it is not a deadline.'},
  fee:{title:'Borrow fee · cost to short sellers',what:'The annualised rate charged to borrow shares, shown here from Interactive Brokers (IBKR).',why:'A rising fee can suggest borrowing is getting harder. A 10% fee means roughly 10% per year, not per day.'},
  available:{title:'Shares available to borrow',what:'How many shares IBKR lists as available for short sellers to borrow at the recorded time.',why:'Low inventory can suggest tighter supply. This is one broker’s inventory, not the whole market. A blank value does not mean zero.'},
  volume:{title:'Today’s volume / normal daily volume',what:'Shares traded today divided by the average full-day volume over 20 trading days. 2× means twice the usual daily volume.',why:'Unusually high volume can show extra interest in a move. During the session, today’s total is still incomplete; this ratio is not adjusted for time of day.'},
  checklist:{title:'Short-squeeze pressure checklist',what:'How many of five checks are met: high short interest, days to cover, borrow fee, low availability and high volume.',why:'More checks mean more reasons to investigate. It is not a squeeze probability or buy signal, and missing data stays unknown.'},
  actions:{title:'Stock actions',what:'The circular arrow refreshes that stock. The chevron opens its research page.',why:'Refresh retrieves new data and updates the draft thesis while keeping your own notes.'},
} satisfies Record<string,{title:string;what:string;why:string;example?:string}>;

type HelpKey=keyof typeof help;
export default function ColumnHeader({topic,children,className}:{topic:HelpKey;children:ReactNode;className?:string}){
  const id=useId(),button=useRef<HTMLButtonElement>(null),card=useRef<HTMLDivElement>(null);
  const [open,setOpen]=useState(false),[pinned,setPinned]=useState(false);
  const [position,setPosition]=useState<{top:number;left:number;width:number}|null>(null);
  const timer=useRef<ReturnType<typeof setTimeout>|null>(null);
  const copy: {title:string;what:string;why:string;example?:string}=help[topic];
  function cancel(){if(timer.current)clearTimeout(timer.current)}
  function close(){cancel();setOpen(false);setPinned(false)}
  function show(){cancel();document.dispatchEvent(new CustomEvent('desk:column-help',{detail:id}));setOpen(true)}
  function leave(){cancel();if(!pinned)timer.current=setTimeout(()=>setOpen(false),180)}
  useEffect(()=>()=>cancel(),[]);
  useEffect(()=>{
    if(!open)return;
    const outside=(e:PointerEvent)=>{if(!button.current?.contains(e.target as Node)&&!card.current?.contains(e.target as Node))close()};
    const key=(e:KeyboardEvent)=>{if(e.key==='Escape'){e.stopPropagation();close()}};
    const other=(e:Event)=>{if((e as CustomEvent).detail!==id)close()};
    document.addEventListener('pointerdown',outside);document.addEventListener('keydown',key);document.addEventListener('desk:column-help',other);
    return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',key);document.removeEventListener('desk:column-help',other)};
  },[open,id]);
  useLayoutEffect(()=>{
    if(!open){setPosition(null);return}
    const place=()=>{
      const rect=button.current?.getBoundingClientRect();if(!rect)return;
      const width=Math.min(300,window.innerWidth-24),height=card.current?.offsetHeight||190;
      const left=Math.max(12,Math.min(rect.left+rect.width/2-width/2,window.innerWidth-width-12));
      const below=rect.bottom+10,top=below+height>window.innerHeight-12?Math.max(12,rect.top-height-10):below;
      setPosition({top,left,width});
    };
    place();window.addEventListener('resize',place);window.addEventListener('scroll',place,true);
    return()=>{window.removeEventListener('resize',place);window.removeEventListener('scroll',place,true)};
  },[open]);
  return <th scope="col" className={className}>
    <button ref={button} type="button" className={`column-help-trigger ${open?'is-open':''}`} aria-label={`${copy.title} explained`} aria-expanded={open} aria-controls={open?id:undefined} aria-describedby={open?id:undefined}
      onPointerEnter={e=>{if(e.pointerType==='mouse')show()}} onPointerLeave={leave}
      onFocus={e=>{if(e.currentTarget.matches(':focus-visible'))show()}} onBlur={()=>{if(!pinned)close()}}
      onClick={()=>{if(pinned)close();else{show();setPinned(true)}}}>
      <span>{children}</span><CircleHelp size={11} aria-hidden="true"/>
    </button>
    {open&&createPortal(<div ref={card} id={id} role="tooltip" className="column-help-card" style={{position:'fixed',...(position||{top:0,left:0,width:300}),visibility:position?'visible':'hidden'}} onPointerEnter={cancel} onPointerLeave={leave}>
      <strong>{copy.title}</strong><p>{copy.what}</p><p className="column-help-why">{copy.why}</p>{copy.example&&<p className="column-help-example">{copy.example}</p>}
    </div>,document.body)}
  </th>;
}
