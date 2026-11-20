import { describe, expect, it } from 'vitest';
import { AUDIT_CATEGORIES, actionLabel, actorLabel } from './auditModel';

describe('audit labels', () => {
  it('names known actions and keeps unknown ones as they are', () => {
    expect(actionLabel('agent.deploy')).not.toBe('agent.deploy');
    expect(actionLabel('device.mac_changed')).not.toBe('device.mac_changed');
    expect(actionLabel('device.mac_conflict_dismissed')).not.toBe('device.mac_conflict_dismissed');
    expect(actionLabel('something.new')).toBe('something.new');
  });

  it('names the caller without ever showing a token', () => {
    expect(actorLabel('api_token:homeassistant')).toContain('homeassistant');
    expect(actorLabel('session')).not.toBe('session');
    expect(actorLabel('unknown-kind')).toBe('unknown-kind');
  });

  it('files every recorded action under a class', () => {
    const recorded = [
      'auth.login', 'auth.password', 'auth.token.create', 'webhook.delete', 'ssh.key.import', 'ssh.connection.update',
      'ssh.known_host.delete', 'ssh.terminal.open', 'agent.deploy', 'agent.patches', 'backup.export', 'database.reset',
      'device.mac_changed', 'device.mac_conflict_dismissed',
    ];
    const prefixes = Object.values(AUDIT_CATEGORIES).flat();
    for (const action of recorded) {
      expect(prefixes.some((p) => action === p || action.startsWith(`${p}.`)), action).toBe(true);
    }
  });
});
