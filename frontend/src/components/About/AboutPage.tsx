import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ExternalLink } from 'lucide-react';
import { api } from '../../api/client';
import { Sidebar } from '../Sidebar';
import { MobileHeader } from '../MobileHeader';
import { ActionRow, SettingsSection } from '../Settings/sections/SettingsParts';

const REPO = 'https://github.com/SleeperXr/GravityLAN';
const LINKS = [
  { href: REPO, label: 'about.link_repo', hint: 'github.com/SleeperXr/GravityLAN' },
  { href: `${REPO}/issues`, label: 'about.link_issues', hint: 'about.link_issues_hint' },
  { href: `${REPO}/releases`, label: 'about.link_releases', hint: 'about.link_releases_hint' },
  { href: `${REPO}/blob/main/CHANGELOG.md`, label: 'about.link_changelog', hint: 'CHANGELOG.md' },
  { href: 'https://hub.docker.com/r/sleeperxr/gravitylan', label: 'about.link_docker', hint: 'sleeperxr/gravitylan' },
];

function OpenLink({ href, label }: { href: string; label: string }) {
  return (
    <a className="btn btn-secondary btn-sm" href={href} target="_blank" rel="noopener noreferrer" aria-label={label}>
      <ExternalLink size={14} aria-hidden="true" />
    </a>
  );
}

/** About GravityLAN: versions, licence and where the project lives (same content as GravityUI's About). */
export function AboutPage() {
  const { t } = useTranslation();
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [versions, setVersions] = useState<{ server?: string; agent?: string }>({});

  useEffect(() => {
    api.getSetupStatus()
      .then((s) => setVersions({ server: s.version, agent: s.agent_version }))
      .catch(() => {});
  }, []);

  const mono = { fontFamily: 'var(--font-mono)', fontSize: '1.2rem', fontWeight: 600 } as const;

  return (
    <div className="app-layout">
      <Sidebar active="about" isOpen={isSidebarOpen} onClose={() => setIsSidebarOpen(false)} />
      <main className="app-main">
        <MobileHeader title={t('about.title')} onMenuClick={() => setIsSidebarOpen(true)} />
        <div className="settings-page">
          <header className="page-header visually-hidden-mobile">
            <h1 className="page-header__title">{t('about.title')}</h1>
            <p className="page-header__subtitle">{t('about.subtitle')}</p>
          </header>

          <SettingsSection id="about-versions" title={t('about.versions')} description={t('about.agent_hint')}>
            <div className="settings-grid">
              <div className="settings-field">
                <div className="form-label">{t('about.server')}</div>
                <div style={mono}>{versions.server ? `v${versions.server}` : '–'}</div>
              </div>
              <div className="settings-field">
                <div className="form-label">{t('about.agent')}</div>
                <div style={mono}>{versions.agent ? `v${versions.agent}` : '–'}</div>
              </div>
            </div>
          </SettingsSection>

          <SettingsSection id="about-project" title={t('about.project')} description={t('about.project_text')}>
            <ActionRow title={t('about.tutorials')} description={t('about.tutorials_hint')}>
              <a className="btn btn-secondary btn-sm" href="/frontend-vue/tutorials">{t('about.tutorials_open')}</a>
            </ActionRow>
            {LINKS.map((link) => (
              <ActionRow key={link.href} title={t(link.label)} description={link.hint.startsWith('about.') ? t(link.hint) : link.hint}>
                <OpenLink href={link.href} label={t(link.label)} />
              </ActionRow>
            ))}
          </SettingsSection>

          <SettingsSection id="about-license" title={t('about.license')} description={t('about.license_text')}>
            <ActionRow title="LICENSE" description="MIT">
              <OpenLink href={`${REPO}/blob/main/LICENSE`} label="LICENSE" />
            </ActionRow>
            <ActionRow title={t('about.third_party')} description="THIRD_PARTY_NOTICES.md">
              <OpenLink href={`${REPO}/blob/main/THIRD_PARTY_NOTICES.md`} label={t('about.third_party')} />
            </ActionRow>
            <ActionRow title={t('about.try_gravityui')} description="/frontend-vue/">
              <a className="btn btn-secondary btn-sm" href="/?ui=vue">GravityUI</a>
            </ActionRow>
          </SettingsSection>
        </div>
      </main>
    </div>
  );
}
