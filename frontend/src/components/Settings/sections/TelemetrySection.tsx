import { useCallback, useEffect, useRef, useState } from 'react';
import { Check, Loader2, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api, type TelemetryPurge, type TelemetryRetention, type TelemetryStatus } from '../../../api/client';
import { useToast } from '../../../context/ToastContext';
import type { Device } from '../../../types';
import { ActionRow, Field, SettingsSection, UnitField, errorText } from './SettingsParts';

type PurgeKind = TelemetryPurge['scope'];

export function formatBytes(bytes: number): string {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const exp = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  const value = bytes / 1024 ** exp;
  return `${value.toFixed(value >= 10 || exp === 0 ? 0 : 1)} ${units[exp]}`;
}

function formatDate(value: string | null, locale: string): string {
  if (!value) return '–';
  // The server sends naive UTC timestamps
  const date = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(locale);
}

function deviceLabel(d: Device): string {
  const name = d.display_name || d.hostname;
  return name && name !== d.ip ? `${name} (${d.ip})` : d.ip;
}

const TIERS = [
  { key: 'raw', tables: ['device_health_samples', 'device_metrics'] },
  { key: 'rollups', tables: ['device_health_rollups', 'device_metrics_rollups'] },
] as const;

/** Two-step buttons: the first click arms one for 5 s, the second runs its action. */
function useArmed() {
  const [armed, setArmed] = useState<PurgeKind | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const arm = (kind: PurgeKind) => {
    clearTimeout(timer.current);
    setArmed(kind);
    timer.current = setTimeout(() => setArmed(null), 5000);
  };
  const disarm = () => {
    clearTimeout(timer.current);
    setArmed(null);
  };
  return { armed, arm, disarm };
}

/** Settings > Measurement data: size of the telemetry database, retention per tier, cleanup. */
export function TelemetrySection() {
  const { t, i18n } = useTranslation();
  const { showToast } = useToast();
  const [status, setStatus] = useState<TelemetryStatus | null>(null);
  const [devices, setDevices] = useState<Device[]>([]);
  const [form, setForm] = useState<Record<keyof TelemetryRetention, string>>({ raw_hours: '', hourly_days: '', daily_days: '' });
  const [olderThan, setOlderThan] = useState('30');
  const [deviceId, setDeviceId] = useState('');
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState<PurgeKind | null>(null);
  const { armed, arm, disarm } = useArmed();

  const applyStatus = useCallback((next: TelemetryStatus) => {
    setStatus(next);
    setForm({
      raw_hours: String(next.retention.raw_hours),
      hourly_days: String(next.retention.hourly_days),
      daily_days: String(next.retention.daily_days),
    });
  }, []);

  useEffect(() => {
    api.getTelemetryStatus().then(applyStatus).catch((err) => {
      console.error('Telemetry status failed:', err);
    });
    api.getDevices()
      .then((list) => setDevices([...list].sort((a, b) => deviceLabel(a).localeCompare(deviceLabel(b)))))
      .catch(() => setDevices([]));
  }, [applyStatus]);

  const isDirty = !!status && (Object.keys(form) as (keyof TelemetryRetention)[])
    .some((key) => form[key] !== String(status.retention[key]));

  const saveRetention = async () => {
    setSaving(true);
    try {
      applyStatus(await api.updateTelemetryRetention({
        raw_hours: Number(form.raw_hours),
        hourly_days: Number(form.hourly_days),
        daily_days: Number(form.daily_days),
      }));
      showToast('success', t('telemetry_settings.saved_title'), t('telemetry_settings.saved_body'));
    } catch (err) {
      showToast('error', t('common.error'), `${t('telemetry_settings.save_failed')} ${errorText(err)}`);
    } finally {
      setSaving(false);
    }
  };

  const purge = async (request: TelemetryPurge) => {
    if (armed !== request.scope) {
      arm(request.scope);
      return;
    }
    disarm();
    setBusy(request.scope);
    const before = status?.sizes.telemetry_bytes ?? 0;
    try {
      const res = await api.purgeTelemetry(request);
      applyStatus(res);
      const rows = Object.values(res.deleted).reduce((sum, n) => sum + n, 0);
      showToast('success', t('telemetry_settings.purged_title'), t('telemetry_settings.purged_body', {
        rows: rows.toLocaleString(i18n.language),
        freed: formatBytes(Math.max(0, before - res.sizes.telemetry_bytes)),
      }));
    } catch (err) {
      showToast('error', t('common.error'), `${t('telemetry_settings.purge_failed')} ${errorText(err)}`);
    } finally {
      setBusy(null);
    }
  };

  const limits = status?.limits;
  const rangeHint = (key: keyof TelemetryRetention, text: string) =>
    limits ? `${text} ${t('telemetry_settings.range', { min: limits[key].min, max: limits[key].max })}` : text;

  const purgeButton = (kind: PurgeKind, request: TelemetryPurge | null, label: string) => (
    <button
      type="button"
      className={`btn btn-danger btn-sm${armed === kind ? ' is-armed' : ''}`}
      onClick={() => request && purge(request)}
      disabled={!request || busy !== null}
    >
      {busy === kind ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <Trash2 size={14} aria-hidden="true" />}
      {armed === kind ? t('telemetry_settings.really') : label}
    </button>
  );

  const days = Number(olderThan);
  const olderThanRequest: TelemetryPurge | null = Number.isInteger(days) && days >= 1
    ? { scope: 'older_than', older_than_days: days } : null;
  const deviceRequest: TelemetryPurge | null = deviceId ? { scope: 'device', device_id: Number(deviceId) } : null;

  return (
    <SettingsSection id="telemetry" title={t('telemetry_settings.title')} description={t('telemetry_settings.description')}>
      <div className="telemetry-sizes">
        <div className="telemetry-size">
          <span className="telemetry-size__label">{t('telemetry_settings.size_telemetry')}</span>
          <span className="telemetry-size__value">{status ? formatBytes(status.sizes.telemetry_bytes) : '…'}</span>
        </div>
        <div className="telemetry-size">
          <span className="telemetry-size__label">{t('telemetry_settings.size_inventory')}</span>
          <span className="telemetry-size__value">{status ? formatBytes(status.sizes.inventory_bytes) : '…'}</span>
        </div>
      </div>

      {status && (
        <ul className="settings-list" aria-label={t('telemetry_settings.tiers_label')}>
          {TIERS.map((tier) => {
            const stats = tier.tables.map((name) => status.tables[name]);
            const rows = stats.reduce((sum, s) => sum + s.rows, 0);
            const oldest = stats.map((s) => s.oldest).filter((v): v is string => !!v).sort()[0] ?? null;
            return (
              <li key={tier.key} className="settings-list__row">
                <div className="settings-list__main">
                  <span className="settings-list__name">{t(`telemetry_settings.tier_${tier.key}`)}</span>
                  <span className="settings-list__meta">{t(`telemetry_settings.tier_${tier.key}_desc`)}</span>
                </div>
                <span className="settings-list__meta telemetry-tier__count">
                  {t('telemetry_settings.rows', { rows: rows.toLocaleString(i18n.language) })}
                  {oldest && ` · ${t('telemetry_settings.since', { date: formatDate(oldest, i18n.language) })}`}
                </span>
              </li>
            );
          })}
        </ul>
      )}

      <div className="settings-grid">
        <UnitField
          id="tel-raw"
          label={t('telemetry_settings.raw_label')}
          hint={rangeHint('raw_hours', t('telemetry_settings.raw_hint'))}
          unit={t('telemetry_settings.unit_hours')}
          value={form.raw_hours}
          onChange={(e) => setForm({ ...form, raw_hours: e.target.value })}
        />
        <UnitField
          id="tel-hourly"
          label={t('telemetry_settings.hourly_label')}
          hint={rangeHint('hourly_days', t('telemetry_settings.hourly_hint'))}
          unit={t('settings.unit_days')}
          value={form.hourly_days}
          onChange={(e) => setForm({ ...form, hourly_days: e.target.value })}
        />
        <UnitField
          id="tel-daily"
          label={t('telemetry_settings.daily_label')}
          hint={rangeHint('daily_days', t('telemetry_settings.daily_hint'))}
          unit={t('settings.unit_days')}
          value={form.daily_days}
          onChange={(e) => setForm({ ...form, daily_days: e.target.value })}
        />
      </div>
      {isDirty && (
        <div className="telemetry-save">
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => status && applyStatus(status)} disabled={saving}>
            {t('settings.discard')}
          </button>
          <button type="button" className="btn btn-primary btn-sm" onClick={saveRetention} disabled={saving}>
            {saving ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <Check size={14} aria-hidden="true" />}
            {t('telemetry_settings.save_retention')}
          </button>
        </div>
      )}

      <ActionRow title={t('telemetry_settings.purge_older_title')} description={t('telemetry_settings.purge_older_desc')}>
        <div className="telemetry-action">
          <div className="input-affix telemetry-action__input">
            <input
              id="tel-older-than"
              type="number"
              inputMode="numeric"
              className="input"
              min={1}
              value={olderThan}
              onChange={(e) => setOlderThan(e.target.value)}
              aria-label={t('telemetry_settings.purge_older_input')}
            />
            <span className="input-affix__suffix">{t('settings.unit_days')}</span>
          </div>
          {purgeButton('older_than', olderThanRequest, t('telemetry_settings.purge_older_button'))}
        </div>
      </ActionRow>

      <ActionRow title={t('telemetry_settings.purge_device_title')} description={t('telemetry_settings.purge_device_desc')}>
        <div className="telemetry-action">
          <Field id="tel-device" label={t('telemetry_settings.purge_device_select')}>
            <select id="tel-device" className="input" value={deviceId} onChange={(e) => setDeviceId(e.target.value)}>
              <option value="">{t('telemetry_settings.purge_device_placeholder')}</option>
              {devices.map((d) => (
                <option key={d.id} value={d.id}>{deviceLabel(d)}</option>
              ))}
            </select>
          </Field>
          {purgeButton('device', deviceRequest, t('telemetry_settings.purge_device_button'))}
        </div>
      </ActionRow>

      <ActionRow title={t('telemetry_settings.purge_all_title')} description={t('telemetry_settings.purge_all_desc')}>
        {purgeButton('all', { scope: 'all' }, t('telemetry_settings.purge_all_button'))}
      </ActionRow>
    </SettingsSection>
  );
}
