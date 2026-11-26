import { searchSymbols } from "../../../lib/providers";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const q = new URL(request.url).searchParams.get("q")?.trim() || "";
  if (q.length < 2) return Response.json({ results: [] }, { headers: { "Cache-Control": "no-store" } });
  try {
    const results = await searchSymbols(q);
    return Response.json({ results }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ results: [], error: "Symbol search is unavailable right now. You can still add a ticker directly." }, { headers: { "Cache-Control": "no-store" } });
  }
}
