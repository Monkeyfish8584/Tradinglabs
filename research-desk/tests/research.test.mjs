import test from 'node:test';
import assert from 'node:assert/strict';
import {parseAnnual,parseQuarterly,parseProfile,classifyBusiness} from '../lib/research-data.ts';
import {composeResearch,canslim,technicals,sma,rsi} from '../lib/research.ts';
import {effective} from '../lib/model.ts';
const table=(headers,rows)=>`<table><tr>${headers.map(h=>`<th>${h}</th>`).join('')}</tr>${rows.map(row=>`<tr>${row.map(c=>`<td>${c}</td>`).join('')}</tr>`).join('')}</table>`;
test('quarterly earnings compare matching year-ago quarter; loss-to-profit does not create fake growth',()=>{
 const h=table(['Fiscal Quarter','Q2 2026','Q1 2026','Q4 2025','Q3 2025','Q2 2025'],[['Earnings Per Share EPS Growth','0.2','0.1','0.05','-0.1','-0.1'],['Revenue Growth','35%','30%','20%','10%','5%']]);
 const s=parseQuarterly(h);assert.equal(s.priorYearQuarterEPS,-.1);assert.equal(s.quarterEPSGrowth,undefined);assert.equal(s.quarterRevenueGrowth,35);
 assert.equal(canslim({ticker:'TEST',name:'Test',sources:{},...s}).criteria[0].status,'partial');
});
test('annual screen ignores TTM and forecasts; keeps completed periods',()=>{
 const h=table(['Fiscal Year','TTM','FY 2025','FY 2024','FY 2023','FY 2022'],[['Earnings Per Share EPS Growth','99','2','1.5','1','0.5']]);
 const s=parseAnnual(h);assert.equal(s.annualEPS[0].period,'FY 2025');assert.equal(s.annualEPS[0].eps,2);assert.equal(s.annualEPS.length,4);
 assert.equal(canslim({ticker:'TEST',name:'Test',sources:{},...s}).criteria[1].status,'pass');
});
test('missing evidence stays unknown and a big price target never earns CANSLIM passes',()=>{
 const r=composeResearch({ticker:'TEST',name:'Test Co',price:10,target:100,sources:{}});
 assert.equal(r.canslim.passes,0);assert.equal(r.canslim.unknown,7);assert.match(r.summary,/not a verified margin of safety/);assert.match(r.priceCommentary.join(' '),/not enough verified price history/);
});
test('automatic company classification uses the core business, not incidental end markets',()=>{
 assert.deepEqual(classifyBusiness('Other Industrial Metals & Mining','Materials','The company explores rare earth minerals. Its products have healthcare and aerospace end uses.').themes,['Metal mining']);
 assert.deepEqual(classifyBusiness('Uranium','Energy','The company produces uranium for nuclear power.').themes,['Nuclear']);
 assert.deepEqual(classifyBusiness('Medical Devices','Healthcare','The company develops robotic surgery systems.').themes,['Robotics','Medical']);
 assert.deepEqual(classifyBusiness('Semiconductors','Technology','The company develops photonics technology.').themes,['Robotics enabler']);
 assert.deepEqual(classifyBusiness('Insurance - Diversified','Financial Services','The company provides insurance. Its subsidiaries hold coal mining assets and nuclear power generation.').themes,[]);
 assert.deepEqual(classifyBusiness('Semiconductors','Technology','The company licenses processor designs for mobile, server and robotics applications.').themes,[]);
});
test('intraday bar is excluded from averages and reference range',()=>{
 const history=Array.from({length:21},(_,i)=>({date:`2026-10-${String(i+1).padStart(2,'0')}`,close:i===20?1000:10,high:i===20?1001:11,low:i===20?999:9,volume:1}));
 const t=technicals({ticker:'TEST',name:'Test',price:12,sessionComplete:false,priceHistory:history,sources:{}});
 assert.equal(t.sma20,10);assert.equal(t.support,9);assert.equal(t.resistance,11);assert.equal(t.sma200,undefined);
});
test('refreshable drafts follow corrected prices while user notes are not part of generated content',()=>{
 const snapshot={ticker:'TEST',name:'Test',price:10,target:20,sources:{}};
 const s=effective({snapshot,manual:{price:{value:5,source:'test',asOf:'2026-10-30T15:00:00Z'}}});
 const r=composeResearch(s,{manualKeys:['price']});assert.match(r.summary,/\$5.00/);assert.match(r.summary,/\+300.0%/);assert.match(r.limitations.join(' '),/Manual corrections/);
 assert.equal(sma([1,2],3),undefined);assert.equal(rsi(Array(20).fill(5)),50);
});

test('profile parser handles > characters in quoted attributes and singular photonic technology',()=>{
 const h='<h1>Company Description</h1><div class="[&amp;>p]:mb-5"><p>Aeluma develops photonic technologies for sensing.</p></div><table><tr><td>Industry</td><td>Semiconductors</td></tr><tr><td>Sector</td><td>Technology</td></tr></table>';
 assert.deepEqual(parseProfile(h).themes,['Robotics enabler']);
});

test('ETF research uses fund risks and marks company CANSLIM inapplicable',()=>{
 const r=composeResearch({ticker:'NUCG.L',name:'VanEck Uranium and Nuclear Technologies UCITS ETF',instrumentType:'ETF',currency:'GBP',price:31.6,eps:-1,target:100,sources:{}});
 assert.equal(r.canslim.notApplicable,true);assert.deepEqual(r.canslim.criteria,[]);
 assert.deepEqual(r.themes,['Nuclear','Metal mining']);assert.match(r.summary,/£31.60/);
 assert.match(r.summary,/net asset value/);assert.doesNotMatch(r.summary,/negative|analyst target|profitability needs verification/i);
 assert.match(r.bearCase.join(' '),/GBP trading line does not by itself remove currency exposure/);
 const generic=composeResearch({ticker:'FUND',name:'A Fund',instrumentType:'ETF',sources:{}});
 assert.equal(generic.canslim.notApplicable,true);assert.deepEqual(generic.themes,['Other']);
});

test('GBP history is not scored against unconverted USD SPY returns',()=>{
 const dates=Array.from({length:250},(_,i)=>new Date(Date.UTC(2025,0,1)+i*1.5*86400000).toISOString().slice(0,10));
 const s={ticker:'FUND',name:'Fund',currency:'GBP',price:20,priceHistory:dates.map((date,i)=>({date,close:10+i/25,high:21,low:9,volume:1})),benchmark:{symbol:'SPY',price:20,closes:dates.map(()=>10),dates},sources:{}};
 assert.equal(technicals(s).relativeReturn,undefined);
 assert.ok(technicals({...s,currency:'USD'}).relativeReturn>0);
});
