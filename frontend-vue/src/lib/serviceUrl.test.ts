import { describe, expect, it } from 'vitest';
import { serviceUrl } from './serviceUrl';

describe('serviceUrl', () => {
  it('fills in the placeholders of allowed links', () => {
    expect(serviceUrl('https://{ip}:{port}', '192.168.1.5', 8006)).toBe('https://192.168.1.5:8006');
    expect(serviceUrl('ssh://{ip}', '10.0.0.2', 22)).toBe('ssh://10.0.0.2');
    expect(serviceUrl('VNC://{ip}:{port}', '10.0.0.2', 5900)).toBe('VNC://10.0.0.2:5900');
  });

  it('refuses script, data and relative links', () => {
    expect(serviceUrl('javascript:alert(document.domain)', '1.2.3.4', 80)).toBeNull();
    expect(serviceUrl(' JaVaScRiPt:alert(1)', '1.2.3.4', 80)).toBeNull();
    expect(serviceUrl('java\tscript:alert(1)', '1.2.3.4', 80)).toBeNull();
    expect(serviceUrl('data:text/html,<script>alert(1)</script>', '1.2.3.4', 80)).toBeNull();
    expect(serviceUrl('vbscript:msgbox', '1.2.3.4', 80)).toBeNull();
    expect(serviceUrl('{ip}:{port}', '1.2.3.4', 80)).toBeNull();
    expect(serviceUrl('', '1.2.3.4', 80)).toBeNull();
  });
});
