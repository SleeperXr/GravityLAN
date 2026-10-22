import { describe, expect, it } from 'vitest';
import { countLevels, filterLogs, parseLogLine } from './logModel';

const line = (level: string, msg: string, n = 1) => parseLogLine(`2026-10-22 21:07:01,123 [${level}] [-] app.scanner: ${msg}`, n);

describe('logModel', () => {
  it('splits a backend line into time, level, logger and message', () => {
    expect(parseLogLine('2026-10-22 21:07:01,123 [WARNING] [a1b2] app.api.agent: Token mismatch: x', 1)).toMatchObject({
      time: '2026-10-22 21:07:01,123', level: 'warning', correlationId: 'a1b2', logger: 'app.api.agent', message: 'Token mismatch: x',
    });
    expect(line('CRITICAL', 'boom').level).toBe('error');
    expect(line('INFO', 'ok').correlationId).toBeNull();
  });

  it('keeps other lines raw and still spots their level', () => {
    expect(parseLogLine('Traceback (most recent call last):', 2)).toMatchObject({ time: null, level: null, message: 'Traceback (most recent call last):' });
    expect(parseLogLine('uvicorn [ERROR] bind failed', 3).level).toBe('error');
  });

  it('filters by minimum level and search text', () => {
    const lines = [line('INFO', 'scan started', 1), line('WARNING', 'slow host', 2), line('ERROR', 'scan failed', 3)];
    expect(filterLogs(lines, 'all', '').map((l) => l.id)).toEqual([1, 2, 3]);
    expect(filterLogs(lines, 'warning', '').map((l) => l.id)).toEqual([2, 3]);
    expect(filterLogs(lines, 'error', '').map((l) => l.id)).toEqual([3]);
    expect(filterLogs(lines, 'all', 'SCAN ').map((l) => l.id)).toEqual([1, 2, 3]);
    expect(filterLogs(lines, 'all', 'Slow').map((l) => l.id)).toEqual([2]);
    expect(countLevels(lines)).toEqual({ warning: 1, error: 1 });
  });
});
