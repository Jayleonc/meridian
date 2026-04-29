export function formatLogTime(timestamp?: string): string {
  if (!timestamp) return "-";

  const brick = timestamp.match(/^\d{2}-\d{2}T(\d{2}:\d{2}:\d{2})/);
  if (brick) return brick[1];

  const iso = Date.parse(timestamp);
  if (!Number.isNaN(iso)) {
    return new Date(iso).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  }

  const fallback = timestamp.match(/(?:T|\s)(\d{2}:\d{2}:\d{2})/);
  return fallback?.[1] ?? timestamp;
}
