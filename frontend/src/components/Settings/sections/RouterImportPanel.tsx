import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Download, ShieldCheck, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { api } from '../../../api/client';
import type { RouterImportPreview, RouterImportProvider, RouterNetworkPreview, RouterSource } from '../../../types';
import { useToast } from '../../../context/ToastContext';
import { errorText } from './SettingsParts';

const SNMP_VERSIONS = ['2c', '3', '1'];
const AUTH_PROTOCOLS = ['SHA', 'SHA256', 'SHA384', 'SHA512', 'SHA224', 'MD5'];
const PRIV_PROTOCOLS = ['AES', 'AES256', 'AES192', 'DES', '3DES'];

/** The networks a fresh preview pre-selects: everything that would add or fill something. */
const importable = (n: RouterNetworkPreview) => n.status === 'new' || n.status === 'update';

/** "new", "already configured as Home", "fills gateway, VLAN of Cams", "too large to scan". */
function statusLabel(net: RouterNetworkPreview, t: TFunction): string {
  if (net.status === 'update') {
    const fields = net.fills.map((f) => (f === 'gateway_ip' ? t('subnet_gateway.gateway') : t('subnet_gateway.vlan'))).join(', ');
    return t('router_import.status_update', { fields, name: net.existing_name ?? '' });
  }
  if (net.status === 'exists') return t('router_import.status_exists', { name: net.existing_name ?? '' });
  return t(`router_import.status_${net.status}`);
}

/**
 * "Import from router": ask a router for its networks (SNMP or the UniFi console API),
 * show them as a preview and add only the picked ones. Existing scan subnets only get an
 * empty gateway/VLAN filled in; nothing changes before "Apply".
 */
export function RouterImportPanel({ onApplied }: { onApplied: () => void | Promise<void> }) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const [sources, setSources] = useState<RouterSource[]>([]);
  const [provider, setProvider] = useState<RouterImportProvider>('snmp');
  const [host, setHost] = useState('');
  const [port, setPort] = useState('');
  const [options, setOptions] = useState<Record<string, string>>({});
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<RouterImportPreview | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<'fetch' | 'apply' | null>(null);
  const [error, setError] = useState<string | null>(null);

  /** Fill the form with the saved connection of a provider (secrets stay empty: "stored"). */
  const prefill = useCallback((list: RouterSource[], key: RouterImportProvider) => {
    const saved = list.find((s) => s.provider === key);
    setHost(saved?.host ?? '');
    setPort(saved?.port != null ? String(saved.port) : '');
    const opts: Record<string, string> = {};
    for (const [k, v] of Object.entries(saved?.options ?? {})) if (v) opts[k] = v;
    setOptions(opts);
    setSecrets({});
  }, []);

  const loadSources = useCallback(async (): Promise<RouterSource[]> => {
    try {
      const list = await api.getRouterSources();
      const valid = Array.isArray(list) ? list : [];
      setSources(valid);
      return valid;
    } catch {
      return [];
    }
  }, []);

  useEffect(() => {
    loadSources().then((list) => {
      if (list[0]) {
        setProvider(list[0].provider);
        prefill(list, list[0].provider);
      }
    });
  }, [loadSources, prefill]);

  const saved = sources.find((s) => s.provider === provider);
  const sameRouter = !!saved && saved.host.trim().toLowerCase() === host.trim().toLowerCase();
  const isStored = (field: string) => sameRouter && !!saved?.stored_secrets.includes(field);

  const switchProvider = (key: RouterImportProvider) => {
    setProvider(key);
    prefill(sources, key);
    setPreview(null);
    setError(null);
  };

  const setOption = (key: string, value: string) => setOptions((prev) => ({ ...prev, [key]: value }));
  const setSecret = (key: string, value: string) => setSecrets((prev) => ({ ...prev, [key]: value }));

  const fetchNetworks = async (extraOptions: Record<string, string> = {}) => {
    if (!host.trim()) return;
    setBusy('fetch');
    setError(null);
    const merged = { ...options, ...extraOptions };
    const filled: Record<string, string> = {};
    for (const [k, v] of Object.entries(secrets)) if (v) filled[k] = v;
    try {
      const result = await api.previewRouterImport({
        provider,
        host: host.trim(),
        port: port.trim() ? Number(port) : null,
        options: merged,
        secrets: filled,
      });
      setOptions(merged);
      setPreview(result);
      setSelected(new Set(result.networks.filter(importable).map((n) => n.cidr)));
      if (result.status === 'ok') {
        setSecrets({});
        await loadSources();
      }
    } catch (err) {
      setPreview(null);
      setError(`${t('router_import.failed')} ${errorText(err)}`);
    } finally {
      setBusy(null);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    fetchNetworks();
  };

  const toggle = (cidr: string, on: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(cidr);
      else next.delete(cidr);
      return next;
    });

  const picked = preview?.status === 'ok' ? preview.networks.filter((n) => importable(n) && selected.has(n.cidr)) : [];

  const apply = async () => {
    if (picked.length === 0) return;
    setBusy('apply');
    try {
      const result = await api.applyRouterImport(
        picked.map(({ cidr, name, gateway_ip, vlan_id }) => ({ cidr, name, gateway_ip, vlan_id })),
      );
      showToast('success', t('notifications.saved'), t('router_import.applied', {
        added: result.added.length, updated: result.updated.length,
      }));
      setPreview(null);
      await onApplied();
    } catch (err) {
      showToast('error', t('common.error'), `${t('router_import.apply_failed')} ${errorText(err)}`);
    } finally {
      setBusy(null);
    }
  };

  const forget = async () => {
    try {
      await api.deleteRouterSource(provider);
      showToast('success', t('notifications.saved'), t('router_import.forgotten'));
      prefill(await loadSources(), provider);
    } catch (err) {
      showToast('error', t('common.error'), errorText(err));
    }
  };

  const secretField = (field: string, label: string, id: string) => (
    <label className="router-import__field" htmlFor={id}>
      <span className="form-label">{label}</span>
      <input
        id={id}
        type="password"
        className="input"
        autoComplete="off"
        value={secrets[field] ?? ''}
        onChange={(e) => setSecret(field, e.target.value)}
        placeholder={isStored(field) ? t('router_import.secret_stored') : ''}
      />
    </label>
  );

  const snmpVersion = options.version || '2c';

  return (
    <div className="router-import">
      <form className="router-import__form" onSubmit={submit} aria-label={t('router_import.title')}>
        <div className="router-import__grid">
          <label className="router-import__field" htmlFor="ri-provider">
            <span className="form-label">{t('router_import.provider')}</span>
            <select id="ri-provider" className="input" value={provider} onChange={(e) => switchProvider(e.target.value as RouterImportProvider)}>
              <option value="snmp">{t('router_import.provider_snmp')}</option>
              <option value="unifi">{t('router_import.provider_unifi')}</option>
            </select>
          </label>
          <label className="router-import__field" htmlFor="ri-host">
            <span className="form-label">{t('router_import.host')}</span>
            <input
              id="ri-host"
              className="input input--mono"
              value={host}
              onChange={(e) => setHost(e.target.value)}
              placeholder="192.168.1.1"
              aria-describedby="ri-host-hint"
            />
          </label>
          <label className="router-import__field router-import__field--narrow" htmlFor="ri-port">
            <span className="form-label">{t('router_import.port')}</span>
            <input
              id="ri-port"
              className="input input--mono"
              type="number"
              min={1}
              max={65535}
              value={port}
              onChange={(e) => setPort(e.target.value)}
              placeholder={provider === 'snmp' ? '161' : '443'}
            />
          </label>
        </div>
        <p className="field-hint" id="ri-host-hint">{t('router_import.host_hint')}</p>

        {provider === 'snmp' ? (
          <>
            <div className="router-import__grid">
              <label className="router-import__field router-import__field--narrow" htmlFor="ri-snmp-version">
                <span className="form-label">{t('router_import.snmp_version')}</span>
                <select id="ri-snmp-version" className="input" value={snmpVersion} onChange={(e) => setOption('version', e.target.value)}>
                  {SNMP_VERSIONS.map((v) => <option key={v} value={v}>v{v}</option>)}
                </select>
              </label>
              {snmpVersion === '3' ? (
                <>
                  <label className="router-import__field" htmlFor="ri-v3-user">
                    <span className="form-label">{t('router_import.v3_user')}</span>
                    <input id="ri-v3-user" className="input" autoComplete="off" value={options.username ?? ''} onChange={(e) => setOption('username', e.target.value)} />
                  </label>
                  <label className="router-import__field router-import__field--narrow" htmlFor="ri-v3-auth-proto">
                    <span className="form-label">{t('router_import.auth_protocol')}</span>
                    <select id="ri-v3-auth-proto" className="input" value={options.auth_protocol || 'SHA'} onChange={(e) => setOption('auth_protocol', e.target.value)}>
                      {AUTH_PROTOCOLS.map((p) => <option key={p} value={p}>{p}</option>)}
                    </select>
                  </label>
                  {secretField('auth_key', t('router_import.auth_key'), 'ri-v3-auth-key')}
                  <label className="router-import__field router-import__field--narrow" htmlFor="ri-v3-priv-proto">
                    <span className="form-label">{t('router_import.priv_protocol')}</span>
                    <select id="ri-v3-priv-proto" className="input" value={options.priv_protocol || 'AES'} onChange={(e) => setOption('priv_protocol', e.target.value)}>
                      {PRIV_PROTOCOLS.map((p) => <option key={p} value={p}>{p}</option>)}
                    </select>
                  </label>
                  {secretField('priv_key', t('router_import.priv_key'), 'ri-v3-priv-key')}
                </>
              ) : (
                secretField('community', t('router_import.community'), 'ri-community')
              )}
            </div>
            <p className="field-hint">{t('router_import.snmp_hint')}</p>
          </>
        ) : (
          <>
            <div className="router-import__grid">
              {secretField('api_key', t('router_import.api_key'), 'ri-api-key')}
              <label className="router-import__field router-import__field--narrow" htmlFor="ri-site">
                <span className="form-label">{t('router_import.site')}</span>
                <input id="ri-site" className="input" value={options.site ?? ''} onChange={(e) => setOption('site', e.target.value)} placeholder="default" />
              </label>
              <label className="router-import__field router-import__field--wide" htmlFor="ri-fingerprint">
                <span className="form-label">{t('router_import.fingerprint')}</span>
                <input
                  id="ri-fingerprint"
                  className="input input--mono"
                  value={options.fingerprint ?? ''}
                  onChange={(e) => setOption('fingerprint', e.target.value)}
                  placeholder={t('router_import.fingerprint_placeholder')}
                />
              </label>
            </div>
            <p className="field-hint">{t('router_import.unifi_hint')}</p>
          </>
        )}

        <div className="router-import__actions">
          <button type="submit" className="btn btn-secondary" disabled={!host.trim() || busy !== null}>
            <Download size={16} aria-hidden="true" /> {busy === 'fetch' ? t('router_import.fetching') : t('router_import.fetch')}
          </button>
          {saved && (
            <button type="button" className="btn btn-danger btn-sm" onClick={forget}>
              <Trash2 size={14} aria-hidden="true" /> {t('router_import.forget')}
            </button>
          )}
        </div>
      </form>

      {error && <p className="router-import__error" role="alert">{error}</p>}

      {preview?.status === 'confirm_certificate' && (
        <div className="router-import__cert" role="alert">
          <p className="form-label">{t('router_import.cert_title')}</p>
          <p className="field-hint">
            {t(preview.reason === 'certificate_mismatch' ? 'router_import.cert_mismatch' : 'router_import.cert_untrusted')}
          </p>
          <code className="router-import__fingerprint">{preview.fingerprint}</code>
          <div>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => fetchNetworks({ fingerprint: preview.fingerprint ?? '' })}
              disabled={busy !== null}
            >
              <ShieldCheck size={14} aria-hidden="true" /> {t('router_import.cert_trust')}
            </button>
          </div>
        </div>
      )}

      {preview?.status === 'ok' && (
        <div className="settings-field">
          <p className="form-label">{t('router_import.preview_title', { host: preview.host, count: preview.networks.length })}</p>
          {preview.networks.length === 0 ? (
            <p className="settings-empty">{t('router_import.preview_empty')}</p>
          ) : (
            <>
              <ul className="settings-list" aria-label={t('router_import.preview_list')}>
                {preview.networks.map((net) => (
                  <li key={net.cidr} className={`settings-list__row${importable(net) ? '' : ' is-paused'}`}>
                    <label className="router-import__pick">
                      <input
                        type="checkbox"
                        checked={importable(net) && selected.has(net.cidr)}
                        disabled={!importable(net)}
                        onChange={(e) => toggle(net.cidr, e.target.checked)}
                        aria-label={t('router_import.select_label', { cidr: net.cidr })}
                      />
                      <span className="settings-list__main">
                        <span className="settings-list__name">
                          <code>{net.cidr}</code>{net.name ? ` · ${net.name}` : ''}
                        </span>
                        <span className="settings-list__meta">
                          {[
                            net.gateway_ip && `${t('subnet_gateway.gateway')} ${net.gateway_ip}`,
                            net.vlan_id != null && `VLAN ${net.vlan_id}`,
                            net.interface,
                          ].filter(Boolean).join(' · ')}
                        </span>
                      </span>
                    </label>
                    <span className={`router-import__status router-import__status--${net.status}`}>{statusLabel(net, t)}</span>
                  </li>
                ))}
              </ul>
              <div className="router-import__actions">
                <button type="button" className="btn btn-primary" onClick={apply} disabled={picked.length === 0 || busy !== null}>
                  {t('router_import.apply', { count: picked.length })}
                </button>
                <p className="field-hint">{t('router_import.apply_hint')}</p>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
