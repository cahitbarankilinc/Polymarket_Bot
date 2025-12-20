import { loadConfig } from './config.js';
import { logMessage, formatTimestamp } from './utils.js';
import { loadState, updateLastRunKey } from './state.js';
import { runOnce } from './bot.js';

const config = loadConfig();
let state = loadState();

interface TimeParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
}

function getTimeParts(date: Date, timezone: string): TimeParts {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone,
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).formatToParts(date);

  const lookup = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  return {
    year: Number(lookup.year),
    month: Number(lookup.month),
    day: Number(lookup.day),
    hour: Number(lookup.hour),
    minute: Number(lookup.minute)
  };
}

function runKey(parts: TimeParts): string {
  return `${parts.year}-${String(parts.month).padStart(2, '0')}-${String(parts.day).padStart(2, '0')}-${String(parts.hour).padStart(2, '0')}-${String(parts.minute).padStart(2, '0')}`;
}

function shouldRun(parts: TimeParts): boolean {
  return [0, 15, 30, 45].includes(parts.minute);
}

async function loop(): Promise<void> {
  const now = new Date();
  const parts = getTimeParts(now, config.timezone);
  const key = runKey(parts);

  if (shouldRun(parts) && state.lastRunKey !== key) {
    logMessage(config.runsDir, `Triggering run for window ${key}`, config.timezone);
    state = await runOnce(config, state);
    state = updateLastRunKey(state, key);
  }
}

logMessage(config.runsDir, `Bot daemon started at ${formatTimestamp(new Date(), config.timezone)} in timezone ${config.timezone}`, config.timezone);
setInterval(() => {
  loop().catch((error) => {
    console.error('Daemon loop error', error);
  });
}, 5000);
