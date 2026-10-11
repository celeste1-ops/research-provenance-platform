// "2 min ago"-style text for an ISO UTC time (local display only).
export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "never";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return iso;
  const s = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 36) return `${h} h ago`;
  return `${Math.round(h / 24)} days ago`;
}

export function shortDate(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 10) : "";
}
