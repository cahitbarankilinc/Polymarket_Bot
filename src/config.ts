import dotenv from 'dotenv';
import path from 'path';

export type Side = 'UP' | 'DOWN';

export interface Config {
  marketUrl: string;
  side: Side;
  limitPrice: number;
  shares: number;
  diffThresholdUsd: number;
  pauseMinutes: number;
  headless: boolean;
  timezone: string;
  storageDir: string;
  runsDir: string;
}

dotenv.config({ path: path.resolve(process.cwd(), '.env') });

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required environment variable ${name}`);
  }
  return value;
}

function parseNumber(name: string): number {
  const raw = requireEnv(name);
  const parsed = Number(raw);
  if (Number.isNaN(parsed)) {
    throw new Error(`Invalid number for ${name}: ${raw}`);
  }
  return parsed;
}

export function loadConfig(): Config {
  const side = requireEnv('SIDE').toUpperCase();
  if (side !== 'UP' && side !== 'DOWN') {
    throw new Error('SIDE must be UP or DOWN');
  }

  const headlessRaw = process.env.HEADLESS ?? 'true';
  const headless = headlessRaw.toLowerCase() === 'true';

  return {
    marketUrl: requireEnv('MARKET_URL'),
    side,
    limitPrice: parseNumber('LIMIT_PRICE'),
    shares: parseNumber('SHARES'),
    diffThresholdUsd: parseNumber('DIFF_THRESHOLD_USD'),
    pauseMinutes: parseNumber('PAUSE_MINUTES'),
    headless,
    timezone: process.env.TIMEZONE || Intl.DateTimeFormat().resolvedOptions().timeZone,
    storageDir: path.resolve(process.cwd(), 'storage'),
    runsDir: path.resolve(process.cwd(), 'runs')
  };
}
