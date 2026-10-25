import { describe, expect, it } from 'vitest';
import { buildInstallCommand } from './ManualInstallCommand';

describe('buildInstallCommand', () => {
  it('pipes into sudo bash for an HTTPS server', () => {
    expect(buildInstallCommand(3, 'abc')).toMatch(/\/api\/agent\/download\/install-sh\/3\?code=abc" \| sudo bash$/);
  });

  it('opts in with ALLOW_INSECURE=1 through env when the server is plain HTTP (#44)', () => {
    expect(buildInstallCommand(3, 'abc', true)).toMatch(/\| sudo env ALLOW_INSECURE=1 bash$/);
  });
});
