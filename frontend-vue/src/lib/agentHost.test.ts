import { describe, expect, it } from 'vitest';
import { pendingHostRelation } from './agentHost';

describe('pendingHostRelation', () => {
  it('tells a host on the same address from one on another', () => {
    expect(pendingHostRelation({ ip: '192.168.1.10', pending_host_ip: '192.168.1.10' })).toBe('same_address');
    expect(pendingHostRelation({ ip: '192.168.1.10', pending_host_ip: '192.168.1.99' })).toBe('other_address');
  });

  it('does not guess when the address of the pending host is not known', () => {
    expect(pendingHostRelation({ ip: '192.168.1.10', pending_host_ip: null })).toBe('unknown');
    expect(pendingHostRelation({ ip: '192.168.1.10' })).toBe('unknown');
    expect(pendingHostRelation({ ip: '192.168.1.10', pending_host_ip: '' })).toBe('unknown');
  });
});
