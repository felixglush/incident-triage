const pad = (value: number) => value.toString().padStart(2, "0");

function parseDate(value?: string | null): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatTime(value?: string | null): string {
  const date = parseDate(value);
  if (!date) return "--";
  return `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`;
}

export function formatDate(value?: string | null): string {
  const date = parseDate(value);
  if (!date) return "--";
  return date.toISOString().slice(0, 10);
}

export function formatDateTime(value?: string | null): string {
  const date = parseDate(value);
  if (!date) return "Updated --";
  return `${date.toISOString().slice(0, 10)} ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())} UTC`;
}
