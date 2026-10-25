import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/api/client';
import { buildInstallCommand, needsInsecureOptIn, requestInstallCode } from './agent';

describe('buildInstallCommand', () => {
  it('fetches the script over HTTPS only from an HTTPS server URL (#44)', () => {
    expect(buildInstallCommand(3, 'abc', 'https://gravity.example/')).toBe(
      `curl --proto '=https' -sSL "https://gravity.example/api/agent/download/install-sh/3?code=abc" | sudo bash`,
    );
  });

  it('uses the server URL, not the address the browser opened the UI with', () => {
    expect(buildInstallCommand(3, 'abc', 'http://192.168.1.5:8000')).toBe(
      'curl -sSL "http://192.168.1.5:8000/api/agent/download/install-sh/3?code=abc" | sudo bash',
    );
  });

  it('adds ALLOW_INSECURE=1 only when the user opted in', () => {
    expect(buildInstallCommand(3, 'abc', 'http://192.168.1.5:8000', true)).toMatch(/\| sudo env ALLOW_INSECURE=1 bash$/);
  });
});

describe('requestInstallCode', () => {
  afterEach(() => vi.restoreAllMocks());

  const enroll = (body: Record<string, unknown>) =>
    vi.spyOn(api, 'createAgentEnrollment').mockResolvedValue({ code: 'abc', expires_in: 60, ...body });

  it('needs an opt-in over plain HTTP unless the server allows it', async () => {
    enroll({ server_url: 'http://192.168.1.5:8000', insecure: true });
    expect(needsInsecureOptIn(await requestInstallCode(3))).toBe(true);

    enroll({ server_url: 'http://192.168.1.5:8000', insecure: true, insecure_allowed: true });
    expect(needsInsecureOptIn(await requestInstallCode(3))).toBe(false);

    enroll({ server_url: 'https://gravity.example', insecure: false });
    expect(needsInsecureOptIn(await requestInstallCode(3))).toBe(false);
  });

  it('refuses a server URL that could break out of the shell command', async () => {
    enroll({ server_url: 'http://evil.example/";reboot;"' });
    await expect(requestInstallCode(3)).rejects.toThrow('Unexpected server URL format');
  });
});
