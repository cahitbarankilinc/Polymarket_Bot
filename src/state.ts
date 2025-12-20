import fs from 'fs';
import path from 'path';
import { ensureDir, formatTimestamp } from './utils.js';

export interface BotState {
  pauseUntil: number | null;
  lastRunKey: string | null;
}

const STATE_PATH = path.resolve(process.cwd(), 'runs', 'state.json');

export function loadState(): BotState {
  try {
    if (fs.existsSync(STATE_PATH)) {
      const data = fs.readFileSync(STATE_PATH, 'utf-8');
      const parsed = JSON.parse(data) as BotState;
      return {
        pauseUntil: parsed.pauseUntil ?? null,
        lastRunKey: parsed.lastRunKey ?? null
      };
    }
  } catch (error) {
    console.error('Failed to load state', error);
  }
  return { pauseUntil: null, lastRunKey: null };
}

export function saveState(state: BotState): void {
  ensureDir(path.dirname(STATE_PATH));
  fs.writeFileSync(STATE_PATH, JSON.stringify(state, null, 2));
}

export function setPause(state: BotState, until: number): BotState {
  const next = { ...state, pauseUntil: until };
  saveState(next);
  return next;
}

export function updateLastRunKey(state: BotState, key: string): BotState {
  const next = { ...state, lastRunKey: key };
  saveState(next);
  return next;
}

export function isPaused(state: BotState, now: number): boolean {
  return state.pauseUntil !== null && now < state.pauseUntil;
}

export function describePause(state: BotState, timezone?: string): string {
  if (!state.pauseUntil) return 'no pause';
  const until = new Date(state.pauseUntil);
  return `paused until ${formatTimestamp(until, timezone)} (${until.toISOString()})`;
}
