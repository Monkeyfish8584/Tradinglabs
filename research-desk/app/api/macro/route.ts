import { env } from "cloudflare:workers";
import { refreshMacro, type MacroData } from "../../../lib/macro";

export const dynamic = "force-dynamic";
function db() { if (!env.DB) throw new Error("Research storage is not available"); return env.DB; }
function json(data: unknown, status = 200) { return Response.json(data, { status, headers: { "Cache-Control": "no-store" } }); }

export async function GET() {
  try {
    const row = await db().prepare("SELECT value FROM desk_settings WHERE key = 'macro'").first<{ value: string }>();
    const macro: MacroData | null = row ? JSON.parse(row.value) : null;
    return json({ macro });
  } catch { return json({ error: "Could not load the macro view. Please try again." }, 503); }
}

export async function POST(request: Request) {
  const origin = request.headers.get("Origin");
  if (origin && origin !== new URL(request.url).origin) return json({ error: "Request origin not allowed" }, 403);
  try {
    const existing = await db().prepare("SELECT value FROM desk_settings WHERE key = 'macro'").first<{ value: string }>();
    if (existing) {
      const prev: MacroData = JSON.parse(existing.value);
      if (Date.now() - Date.parse(prev.fetchedAt) < 10 * 60 * 1000) return json({ macro: prev, throttled: true });
    }
    const macro = await refreshMacro();
    await db().prepare("INSERT INTO desk_settings (key,value) VALUES ('macro',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value").bind(JSON.stringify(macro)).run();
    return json({ macro });
  } catch (error) {
    console.error("Macro refresh failed", error instanceof Error ? error.message : "unknown");
    return json({ error: "The macro refresh could not be completed. Previous values are retained." }, 500);
  }
}
