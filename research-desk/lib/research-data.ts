import type { Snapshot } from './model';
import {numberValue,tableRows,textOnly} from './parsing.ts';

export function classifyBusiness(industry:string,sector:string,description:string): {themes:string[];businessFocus:string} {
  // A diversified insurer's subsidiary assets are not its primary investment theme.
  if(/financial services/i.test(sector)||/insurance|banks|financial conglomerates/i.test(industry))return {themes:[],businessFocus:industry.toLowerCase()||'financial services'};
  const primary=description.split(/(?<=[.!?])\s+/).slice(0,3).join(' ');
  const text=`${industry} ${primary}`.toLowerCase();
  const themes:string[]=[];
  if(/uranium|nuclear (power|reactor|energy|fuel)|small modular reactor/.test(text))themes.push('Nuclear');
  if(/\bmining\b|\bminerals?\b|\brare earth\b|gold exploration|copper exploration/.test(text))themes.push('Metal mining');
  if(!/semiconductor/i.test(industry)&&/robotics|robotic|autonomous (mobile|industrial)|industrial automation/.test(text))themes.push('Robotics');
  if(/healthcare|medical|biotechnology|drug manufacturers/.test(`${industry} ${sector}`.toLowerCase()))themes.push('Medical');
  if(!themes.includes('Robotics')&&/photonics?|lidar|optical sensor|photodetector/.test(text))themes.push('Robotics enabler');
  let businessFocus=industry?industry.toLowerCase():'a business whose operating model needs further verification';
  if(/rare earth/.test(text))businessFocus='rare-earth materials and the critical-minerals supply chain';
  else if(/small modular reactor/.test(text))businessFocus='small modular reactor technology and project development';
  else if(/uranium/.test(text))businessFocus='uranium and the nuclear fuel supply chain';
  else if(/immunotherap|oncology/.test(text))businessFocus='cancer treatment and immunotherapy';
  else if(/diabetes|obesity/.test(text))businessFocus='diabetes, obesity and metabolic treatments';
  else if(/photonics?/.test(text))businessFocus='photonics and compound-semiconductor technology';
  else if(themes.includes('Robotics'))businessFocus='robotics and automation';
  return {themes,businessFocus};
}
export function parseProfile(html:string):Partial<Snapshot>{
  const match=html.match(/Company Description<\/h1>\s*<div\b(?:[^>"\']|"[^"]*"|\'[^\']*\')*>([\s\S]*?)<\/div>/i);
  if(!match)throw new Error('Company profile unavailable');
  const rows=tableRows(html),value=(label:string)=>rows.find(r=>r[0]?.text===label)?.[1];
  const industry=value('Industry')?.text||'',sector=value('Sector')?.text||'';
  const website=value('Website')?.raw.match(/href="(https?:[^"<>]+)"/)?.[1];
  // Use the description to classify the operating business; do not republish it.
  return {industry,sector,companyWebsite:website,...classifyBusiness(industry,sector,textOnly(match[1]))};
}
export function parseQuarterly(html:string):Partial<Snapshot>{
  const rows=tableRows(html),headers=rows.find(r=>r[0]?.text==='Fiscal Quarter');
  if(!headers)throw new Error('Quarterly financials unavailable');
  const current=headers[1]?.text.match(/^Q([1-4])\s+(\d{4})$/);
  const epsRow=rows.find(r=>/^Earnings Per Share(?: EPS Growth)?$/.test(r[0]?.text||''));
  if(!current||!epsRow)throw new Error('Quarterly EPS series unavailable');
  const previousIndex=headers.findIndex(r=>r.text===`Q${current[1]} ${Number(current[2])-1}`);
  const quarterEPS=numberValue(epsRow[1]?.text),priorYearQuarterEPS=previousIndex>0?numberValue(epsRow[previousIndex]?.text):undefined;
  const growthRow=rows.find(r=>r[0]?.text==='Revenue Growth');
  return {latestQuarter:headers[1].text,quarterEPS,priorYearQuarterEPS,
    quarterEPSGrowth:quarterEPS!=null&&priorYearQuarterEPS!=null&&priorYearQuarterEPS>0?(quarterEPS/priorYearQuarterEPS-1)*100:undefined,
    quarterRevenueGrowth:numberValue(growthRow?.[1]?.text),financialCurrency:html.match(/Millions\s+([A-Z]{3})\./)?.[1]};
}
export function parseAnnual(html:string):Partial<Snapshot>{
  const rows=tableRows(html),headers=rows.find(r=>r[0]?.text==='Fiscal Year');
  const epsRow=rows.find(r=>/^Earnings Per Share(?: EPS Growth)?$/.test(r[0]?.text||''));
  if(!headers||!epsRow)throw new Error('Annual EPS series unavailable');
  const annualEPS=headers.flatMap((c,i)=>/^FY \d{4}$/.test(c.text)?[{period:c.text,eps:numberValue(epsRow[i]?.text)??null}]:[]).slice(0,4);
  if(!annualEPS.length)throw new Error('Completed annual EPS periods unavailable');
  return {annualEPS};
}
export function parseHeadlines(html:string):Partial<Snapshot>{
  const headlines:NonNullable<Snapshot['headlines']>=[];
  for(const m of html.matchAll(/<h3\b[^>]*>\s*<a\b[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>\s*<\/h3>([\s\S]*?)(?=<h3\b|$)/gi)){
    const rawTitle=textOnly(m[2]);
    const words=rawTitle.split(' '),title=words.slice(0,12).join(' ')+(words.length>12?'…':'');
    let url:string;try{url=new URL(m[1],'https://stockanalysis.com').href}catch{continue}
    if(!/^https:\/\//.test(url)||/transcripts/.test(url))continue;
    const date=m[3].match(/title="(\d{4}-\d\d-\d\dT[^"<>]+|[A-Za-z]{3} \d{1,2}, \d{4}[^"<>]*)"/)?.[1];
    headlines.push({title,url,date});if(headlines.length===2)break;
  }
  return {headlines};
}
