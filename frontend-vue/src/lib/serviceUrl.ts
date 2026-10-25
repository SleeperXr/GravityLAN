/**
 * Schemes a service badge may open (#42), the same list the backend enforces on
 * url_template. Checked again here so links stored before that check, or restored
 * from an old backup, can never run javascript: or data: URLs in the dashboard.
 */
export const SAFE_SERVICE_SCHEMES = ['http:', 'https:', 'ssh:', 'sftp:', 'scp:', 'ftp:', 'smb:', 'rdp:', 'vnc:'];

/** The service link with {ip} and {port} filled in, or null when it is empty or unsafe. */
export function serviceUrl(template: string, ip: string, port: number): string | null {
  const url = template.replace('{ip}', ip).replace('{port}', String(port));
  if (!url) return null;
  try {
    // Parsed the way the browser would navigate it (control characters, case, whitespace)
    return SAFE_SERVICE_SCHEMES.includes(new URL(url).protocol) ? url : null;
  } catch {
    return null;
  }
}
