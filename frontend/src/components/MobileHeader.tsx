import { Menu } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface MobileHeaderProps {
  title: string;
  onMenuClick: () => void;
}

/** Phone app bar: brand and page title on the left, the menu within thumb reach on the right. */
export function MobileHeader({ title, onMenuClick }: MobileHeaderProps) {
  const { t } = useTranslation();

  return (
    <header className="mobile-header mobile-only">
      <div className="mobile-header__text">
        <span className="mobile-header__brand">{t('app.title')}</span>
        <span className="mobile-header__title">{title}</span>
      </div>
      <button type="button" className="mobile-menu-btn" onClick={onMenuClick} aria-label={t('sidebar.open_menu')}>
        <Menu size={20} aria-hidden="true" />
      </button>
    </header>
  );
}
