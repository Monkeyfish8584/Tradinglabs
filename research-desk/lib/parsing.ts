export function textOnly(s: string): string {
  return s.replace(/<!--[\s\S]*?-->/g, "").replace(/<[^>]*>/g, " ").replace(/&amp;/g, "&").replace(/&nbsp;|&#160;/g, " ").replace(/&#39;|&apos;/g, "'").replace(/&quot;/g, '"').replace(/\s+/g, " ").trim();
}
export function numberValue(s: string | undefined): number | undefined {
  if (!s || /^(n\/a|--|—|-)$/i.test(s.trim())) return undefined;
  const match = s.replace(/[$,%+\s]/g, "").match(/^(-?[\d.]+)([TBMK])?$/i);
  if (!match) return undefined;
  const n = Number(match[1]) * ({ T: 1e12, B: 1e9, M: 1e6, K: 1e3 }[match[2]?.toUpperCase() as "T"] || 1);
  return Number.isFinite(n) ? n : undefined;
}
export function tableRows(html: string): { text: string; raw: string }[][] {
  return [...html.replace(/<!--[\s\S]*?-->/g, "").matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)]
    .map(row => [...row[1].matchAll(/<t[dh]\b([^>]*)>([\s\S]*?)<\/t[dh]>/gi)].map(c => ({ text: textOnly(c[2]), raw: c[1] + ">" + c[2] })));
}
