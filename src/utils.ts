import fs from 'fs';
import path from 'path';

export function ensureDir(dir: string): void {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

export function parsePrice(text: string): number {
  const cleaned = text.replace(/[\s$€£₺₿]/g, '');
  const numeric = cleaned.replace(/[^0-9.,-]/g, '');

  if (!numeric) {
    throw new Error(`Unable to parse price from empty text: ${text}`);
  }

  const lastComma = numeric.lastIndexOf(',');
  const lastDot = numeric.lastIndexOf('.');
  let normalized = numeric;

  if (lastComma > -1 && lastDot > -1) {
    normalized = lastComma > lastDot ? numeric.replace(/\./g, '').replace(',', '.') : numeric.replace(/,/g, '');
  } else if (lastComma > -1) {
    normalized = numeric.replace(/,/g, '.');
  }

  const value = Number(normalized);
  if (Number.isNaN(value)) {
    throw new Error(`Unable to parse price from: ${text}`);
  }
  return value;
}

export function formatTimestamp(date: Date = new Date(), timezone?: string): string {
  return new Intl.DateTimeFormat('sv-SE', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
    .format(date)
    .replace(' ', 'T');
}

export function logMessage(runsDir: string, message: string, timezone?: string): void {
  ensureDir(runsDir);
  const timestamped = `[${formatTimestamp(timezone)}] ${message}\n`;
  const logPath = path.join(runsDir, 'bot.log');
  fs.appendFileSync(logPath, timestamped);
  console.log(timestamped.trim());
}

export function sanitizeFileName(label: string): string {
  return label.replace(/[^a-z0-9-_]/gi, '_');
}
