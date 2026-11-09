import test from 'node:test';
import assert from 'node:assert/strict';
import { numberValue, parseStatistics, parseForecast, parseBorrow, parseReportedShort, refreshSnapshot } from '../lib/providers.ts';
import { effective, squeezeChecks, upside, validTicker } from '../lib/model.ts';
const stats='<table>'+[
 ['Market Cap','8.67B','8669460713'],['Shares Outstanding','1.06B','1059836273'],['Loss Per Share','-$0.99','-0.989'],
 ['Short Interest','122.95M','122945839'],['Short % of Float','30.23%','30.231%'],['Short Ratio (days to cover)','7.96','7.96'],
 ['Forward PE','n/a','n/a'],['Price Target','$14.25','14.25']
].map(([label,value,title])=>`<tr><td><!--[1--><span>${label}</span></td><td title="${title}">${value}</td></tr>`).join('')+'</table>';
const short='<table><tr><td>2026-10-15</td><td>106.73</td><td>122,945,839</td><td>7.15</td><td>-1,146,363</td><td>-0.92</td><td>1,059,836,273</td><td>115,196,180</td></tr><tr><td>2026-09-30</td><td>109.01</td><td>124,092,202</td><td>8.88</td><td>-1,315,990</td><td>-1.05</td><td>1,059,836,273</td><td>113,839,017</td></tr></table>';
test('statistics use exact precision, keep negative EPS and do not invent missing forward PE',()=>{
 const s=parseStatistics(stats);assert.equal(s.shortShares,122945839);assert.equal(s.shortFloatPct,30.231);assert.equal(s.eps,-.989);assert.equal(s.forwardPE,undefined);
 assert.equal(parseStatistics(stats.replace('Loss Per Share','Earnings Per Share (EPS)').replace('-0.989','3.858')).eps,3.858);
 assert.throws(()=>parseStatistics('<html>Blocked</html>'));
});
test('borrow parser uses the latest dated broker snapshot, handles nested comments, zero availability and EDT',()=>{
 const s=parseBorrow('<p class="symbol-profile bf-summary">As of <strong>2026-10-30 02:08:30 PM EDT</strong>, there were <strong>0</strong> shares available with a fee of <strong>0.48<!-- -->%</strong>.</p>');
 assert.equal(s.borrowAt,'2026-10-30T18:08:30.000Z');assert.equal(s.available,0);assert.equal(s.borrowFee,.48);
 assert.throws(()=>parseBorrow('<table><tr><td>No update</td></tr></table>'));
});
test('SI dates are attached only when the share count agrees; float disagreement is flagged',()=>{
 const s=parseReportedShort(short,parseStatistics(stats));assert.equal(s.shortDate,'2026-10-15');assert.equal(s.shortChangePct,-.92);assert.equal(s.floatDisagreement,true);
 assert.throws(()=>parseReportedShort(short,{shortShares:100}));
});
test('target table distinguishes average from median',()=>{
 const s=parseForecast('<table><tr><th>Target</th><th>Low</th><th>Average</th><th>Median</th><th>High</th></tr><tr><td>Price</td><td>$12</td><td>$14.25</td><td>$14.5</td><td>$16</td></tr></table>');
 assert.equal(s.target,14.25);assert.equal(s.targetMedian,14.5);
});
test('failed refresh retains data and source dates and reports the failure',async()=>{
 const oldFetch=globalThis.fetch;globalThis.fetch=async()=>new Response('unavailable',{status:503});
 try{
  const s=await refreshSnapshot('TEST',{ticker:'TEST',name:'Test',price:9,target:18,borrowFee:5,quoteAt:'2026-10-29T16:00:00Z',sources:{quote:{name:'Yahoo',url:'https://example.com',fetchedAt:'2026-10-29T16:01:00Z'}}});
  assert.equal(s.price,9);assert.equal(s.target,18);assert.equal(s.quoteAt,'2026-10-29T16:00:00Z');assert.equal(s.sources.quote.fetchedAt,'2026-10-29T16:01:00Z');assert.match(s.sources.quote.error,/503/);
 }finally{globalThis.fetch=oldFetch}
});
test('missing data is unknown, available zero is known and price target upside is computed correctly',()=>{
 const s={ticker:'TEST',name:'Test',price:10,target:25,available:0,sources:{}};
 assert.equal(upside(s),150);assert.equal(squeezeChecks(s).filter(c=>c.passed).length,1);assert.equal(squeezeChecks(s).filter(c=>!c.known).length,4);
 assert.equal(upside({...s,price:0}),null);assert.equal(numberValue('n/a'),undefined);assert.equal(numberValue('1.2M'),1200000);
 assert.equal(validTicker('BRK-B'),true);assert.equal(validTicker('../../x'),false);
});
