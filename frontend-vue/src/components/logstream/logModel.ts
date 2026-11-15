/**
 * Backend log lines as streamed by /api/logs/ws, formatted by the backend as
 * `%(asctime)s [%(levelname)s] [%(correlation_id)s] %(name)s: %(message)s`, the time as ISO 8601
 * in UTC (`2026-11-15T08:45:36.123Z`) so the browser can show it in the chosen time zone.
 */
export type LogLevel = 'debug' | 'info' | 'warning' | 'error';

export interface LogLine {
  id: number;
  raw: string;
  /** The time as the backend wrote it */
  time: string | null;
  /** The moment, when the time carries its zone; older backends sent server-local time without one */
  date: Date | null;
  level: LogLevel | null;
  correlationId: string | null;
  logger: string | null;
  message: string;
}

export const MAX_LINES = 500;

const LINE = /^(\d{4}-\d{2}-\d{2}[T ][\d:,.]+(?:Z|[+-]\d{2}:?\d{2})?) \[(\w+)\] \[([^\]]*)\] ([^:\s]+): ([\s\S]*)$/;

function toLevel(name: string): LogLevel | null {
  const upper = name.toUpperCase();
  if (upper === 'DEBUG') return 'debug';
  if (upper === 'INFO') return 'info';
  if (upper === 'WARNING' || upper === 'WARN') return 'warning';
  if (upper === 'ERROR' || upper === 'CRITICAL') return 'error';
  return null;
}

/** The moment of an ISO time with a zone ("…Z", "…+01:00"), null for a time without one. */
export function parseLogTime(time: string): Date | null {
  if (!/(?:Z|[+-]\d{2}:?\d{2})$/.test(time)) return null;
  const date = new Date(time.replace(' ', 'T').replace(',', '.'));
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Split a line into its parts; lines in another shape (tracebacks, uvicorn) keep only the raw text. */
export function parseLogLine(raw: string, id: number): LogLine {
  const match = LINE.exec(raw);
  if (!match) {
    const level = /\[(ERROR|CRITICAL)\]/.test(raw) ? 'error' : /\[WARN(ING)?\]/.test(raw) ? 'warning' : null;
    return { id, raw, time: null, date: null, level, correlationId: null, logger: null, message: raw };
  }
  const [, time, level, correlationId, logger, message] = match;
  return { id, raw, time, date: parseLogTime(time), level: toLevel(level), correlationId: correlationId && correlationId !== '-' ? correlationId : null, logger, message };
}

/** Lines at or above the chosen level ('all' shows everything) that contain the search text. */
export function filterLogs(lines: LogLine[], minLevel: 'all' | 'warning' | 'error', query: string): LogLine[] {
  const q = query.trim().toLowerCase();
  return lines.filter((line) => {
    if (minLevel === 'error' && line.level !== 'error') return false;
    if (minLevel === 'warning' && line.level !== 'warning' && line.level !== 'error') return false;
    return !q || line.raw.toLowerCase().includes(q);
  });
}

export function countLevels(lines: LogLine[]): { warning: number; error: number } {
  let warning = 0;
  let error = 0;
  for (const line of lines) {
    if (line.level === 'warning') warning++;
    else if (line.level === 'error') error++;
  }
  return { warning, error };
}
