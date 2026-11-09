import { env } from "cloudflare:workers";
import { refreshSnapshot } from "../../../lib/providers";
import { effective, MANUAL_NUMBERS, STAGES, validTicker, type Stock, type Snapshot } from "../../../lib/model";
import {composeResearch} from "../../../lib/research";
import bootstrap from "../../../lib/bootstrap.json";

export const dynamic = "force-dynamic";
function db() { if (!env.DB) throw new Error("Research storage is not available"); return env.DB; }
function json(data: unknown, status = 200) { return Response.json(data, { status, headers: { "Cache-Control": "no-store" } }); }
function parseRow(r: any, history: any[] = []): Stock {
  return { ticker: r.ticker, name: r.name, addedAt: r.added_at, snapshot: JSON.parse(r.snapshot), notes: r.notes, stage: r.stage, manual: JSON.parse(r.manual), history: history.map(h => ({recordedAt:h.recorded_at,target:h.target})), research: r.research && r.research !== "{}" ? JSON.parse(r.research) : composeResearch(effective({snapshot:JSON.parse(r.snapshot),manual:JSON.parse(r.manual)}),{manualKeys:Object.keys(JSON.parse(r.manual))}) };
}
async function readStock(ticker: string) {
  const row = await db().prepare("SELECT * FROM desk_stocks WHERE ticker = ?").bind(ticker).first();
  if (!row) return null;
  const history = await db().prepare("SELECT recorded_at,target FROM target_history WHERE ticker = ? ORDER BY id DESC LIMIT 90").bind(ticker).all();
  return parseRow(row, history.results.reverse());
}
export async function GET() {
  try {
    const initialized = await db().prepare("SELECT value FROM desk_settings WHERE key = 'initialized'").first();
    if (!initialized) {
      const seeds = (bootstrap as Snapshot[]).map(s => db().prepare("INSERT OR IGNORE INTO desk_stocks (ticker,name,added_at,snapshot,notes,stage,manual,research) VALUES (?,?,?,?,?,?,?,?)").bind(s.ticker,s.name,new Date().toISOString(),JSON.stringify(s),"","Watching","{}",JSON.stringify(composeResearch(s))));
      await db().batch([...seeds, db().prepare("INSERT OR IGNORE INTO desk_settings (key,value) VALUES ('initialized','1')")]);
    }
    const { results } = await db().prepare("SELECT * FROM desk_stocks ORDER BY added_at,ticker").all();
    const histories = await db().prepare("SELECT ticker,recorded_at,target FROM target_history ORDER BY id").all();
    return json({ stocks: results.map((r: any) => parseRow(r,histories.results.filter((h: any) => h.ticker===r.ticker).slice(-90))) });
  } catch { return json({ error: "Could not load the watchlist. Please try again." }, 503); }
}
export async function POST(request: Request) {
  const origin = request.headers.get("Origin");
  if (origin && origin !== new URL(request.url).origin) return json({error:"Request origin not allowed"},403);
  if (!(request.headers.get("content-type") || "").includes("application/json")) return json({error:"JSON required"},415);
  try {
    const body = await request.json() as any;
    const ticker = String(body.ticker || "").trim().toUpperCase();
    if (!validTicker(ticker)) return json({error:"Enter a valid ticker, for example USAR or NVO."},400);
    const old = await readStock(ticker);
    if (body.action === "add") {
      if (old) return json({error:"That ticker is already on your desk."},409);
      const count = await db().prepare("SELECT COUNT(*) AS n FROM desk_stocks").first<{n:number}>();
      if ((count?.n || 0) >= 100) return json({error:"Your desk supports up to 100 stocks."},400);
      const snapshot = await refreshSnapshot(ticker);
      if (snapshot.price == null) return json({error:"Could not verify this ticker. Check its Yahoo Finance symbol, or try again if the feed is unavailable."},422);
      await db().prepare("INSERT INTO desk_stocks (ticker,name,added_at,snapshot,notes,stage,manual,research) VALUES (?,?,?,?,?,?,?,?)").bind(ticker,snapshot.name,new Date().toISOString(),JSON.stringify(snapshot),"","Watching","{}",JSON.stringify(composeResearch(snapshot))).run();
      if (snapshot.target != null) await db().prepare("INSERT INTO target_history (ticker,recorded_at,target) VALUES (?,?,?)").bind(ticker,new Date().toISOString(),snapshot.target).run();
    } else {
      if (!old) return json({error:"Ticker not found"},404);
      if (body.action === "refresh") {
        if (Date.now() - Date.parse(old.snapshot.attemptedAt || "2000-01-01") < 20000) return json({stock:old,throttled:true});
        const snapshot = await refreshSnapshot(ticker,old.snapshot);
        await db().prepare("UPDATE desk_stocks SET name = ?,snapshot = ?,research = ? WHERE ticker = ?").bind(snapshot.name,JSON.stringify(snapshot),JSON.stringify(composeResearch(effective({snapshot,manual:old.manual}),{manualKeys:Object.keys(old.manual)})),ticker).run();
        if (snapshot.target != null && !snapshot.sources.forecast?.error && snapshot.sources.forecast?.fetchedAt === snapshot.attemptedAt && snapshot.target !== old.history.at(-1)?.target) {
          await db().prepare("INSERT INTO target_history (ticker,recorded_at,target) VALUES (?,?,?)").bind(ticker,new Date().toISOString(),snapshot.target).run();
        }
      } else if (body.action === "edit") {
        const notes = typeof body.notes === "string" ? body.notes.slice(0,12000) : old.notes;
        const stage = STAGES.includes(body.stage) ? body.stage : old.stage;
        await db().prepare("UPDATE desk_stocks SET notes = ?,stage = ? WHERE ticker = ?").bind(notes,stage,ticker).run();
      } else if (body.action === "manual") {
        const manual: Stock["manual"] = {};
        const hasValues = body.values && Object.values(body.values).some((v: any) => v !== "" && v != null);
        if (hasValues) {
          if (typeof body.source !== "string" || !body.source.trim() || body.source.length > 500 || !Number.isFinite(Date.parse(body.asOf)) || Date.parse(body.asOf) > Date.now()+60000) return json({error:"Add a source and a valid observation time, no later than now."},400);
          for (const key of MANUAL_NUMBERS) {
            const raw = body.values?.[key];
            if (raw === "" || raw == null) continue;
            const n = Number(raw);
            if (!Number.isFinite(n) || (key !== "eps" && n < 0) || (["price","target","forwardPE"].includes(key) && n <= 0)) return json({error:`Check the value for ${key}.`},400);
            if (["available","shortShares"].includes(key) && !Number.isInteger(n)) return json({error:"Share counts must be whole numbers."},400);
            manual[key] = {value:n,source:body.source.trim(),asOf:new Date(body.asOf).toISOString()};
          }
          if (body.values?.shortDate) {
            if (!/^\d{4}-\d\d-\d\d$/.test(body.values.shortDate) || !Number.isFinite(Date.parse(body.values.shortDate))) return json({error:"Use a valid SI settlement date."},400);
            manual.shortDate = {value:body.values.shortDate,source:body.source.trim(),asOf:new Date(body.asOf).toISOString()};
          }
        }
        await db().prepare("UPDATE desk_stocks SET manual = ?,research = ? WHERE ticker = ?").bind(JSON.stringify(manual),JSON.stringify(composeResearch(effective({snapshot:old.snapshot,manual}),{manualKeys:Object.keys(manual)})),ticker).run();
      } else if (body.action === "delete") {
        await db().batch([db().prepare("DELETE FROM target_history WHERE ticker = ?").bind(ticker),db().prepare("DELETE FROM desk_stocks WHERE ticker = ?").bind(ticker)]);
        return json({deleted:ticker});
      } else return json({error:"Unknown action"},400);
    }
    return json({stock:await readStock(ticker)});
  } catch (error) {
    console.error("Desk operation failed",error instanceof Error ? error.message : "unknown");
    return json({error:"The update could not be saved. Your previous data is retained; please try again."},500);
  }
}
