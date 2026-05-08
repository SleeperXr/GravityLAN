import { Menu } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface MobileHeaderProps {
  title: string;
  onMenuClick: () => void;
}

export function MobileHeader({ title, onMenuClick }: MobileHeaderProps) {
  const { t } = useTranslation();
  
  return (
    <header className="mobile-header mobile-only">
      <button className="mobile-menu-btn" onClick={onMenuClick}>
        <Menu size={24} />
      </button>
      <div className="mobile-header__title">{title}</div>
      <div style={{ width: 40 }} /> {/* Spacer for balance */}
    </header>
  );
}
