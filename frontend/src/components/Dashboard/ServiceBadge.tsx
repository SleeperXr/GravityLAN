import { useState } from 'react';
import type { Service } from '../../types';
import { 
  Terminal, Globe, Folder, Monitor, Shield, 
  Database, Activity, Lock, Cpu, Server, 
  ArrowRightLeft, ExternalLink, Settings 
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useToast } from '../../context/ToastContext';

interface ServiceBadgeProps {
  service: Service;
  ip: string;
  disabled?: boolean;
  isMini?: boolean;
}

const ICON_MAP: Record<string, any> = {
  'ssh': Terminal,
  'http': Globe,
  'https': Lock,
  'rdp': Monitor,
  'smb': Folder,
  'scp': ArrowRightLeft,
  'proxmox': Server,
  'esxi': Cpu,
  'synology': Database,
  'sophos_admin': Shield,
  'securepoint': Shield,
  'cockpit': Activity,
  'webmin': Settings,
  'home_assistant': Globe,
};

// Fallback for names
const getIcon = (service: Service) => {
  const protocol = service.protocol.toLowerCase();
  const name = service.name.toLowerCase();
  
  if (ICON_MAP[protocol]) return ICON_MAP[protocol];
  
  for (const key in ICON_MAP) {
    if (name.includes(key)) return ICON_MAP[key];
  }
  
  return ExternalLink;
};

export function ServiceBadge({ service, ip, disabled, isMini }: ServiceBadgeProps) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const [isCopied, setIsCopied] = useState(false);
  
  const url = service.url_template
    .replace('{ip}', ip)
    .replace('{port}', String(service.port));

  const Icon = getIcon(service);
  const isSmb = service.protocol.toLowerCase() === 'smb';
  const isRdp = service.protocol.toLowerCase() === 'rdp';

  const copyToClipboard = async (text: string) => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        // Fallback for non-secure contexts (HTTP)
        const textArea = document.createElement("textarea");
        textArea.value = text;
        document.body.appendChild(textArea);
        textArea.select();
        try {
          document.execCommand('copy');
        } catch (err) {
          console.error('Fallback copy failed', err);
        }
        document.body.removeChild(textArea);
      }
      setIsCopied(true);
      setTimeout(() => setIsCopied(false), 2000);
      showToast('info', t('notifications.copied'), `${text} ${t('notifications.copied_text')}`);
    } catch (err) {
      console.error('Failed to copy!', err);
      showToast('error', t('common.error'), t('notifications.save_failed'));
    }
  };

  return (
    <a
      href={isSmb ? '#' : url}
      className={`service-badge ${disabled ? 'disabled' : ''} ${isCopied ? 'copied' : ''} ${isMini ? 'is-mini' : ''}`}
      style={{ 
        backgroundColor: isCopied ? '#22c55e' : (service.color || '#34495e'),
        textDecoration: 'none',
        display: 'flex',
        alignItems: 'center',
        gap: isMini ? '4px' : '6px',
        padding: isMini ? '4px 6px' : '4px 8px',
        borderRadius: '4px',
        color: 'white',
        fontSize: '0.75rem',
        border: 'none',
        transition: 'all 0.2s',
        cursor: disabled ? 'not-allowed' : 'pointer',
        boxShadow: isCopied ? '0 0 10px rgba(34, 197, 94, 0.5)' : 'none',
        height: isMini ? '24px' : 'auto'
      }}
      onClick={(e) => {
        if (disabled) {
          e.preventDefault();
          return;
        }

        if (isSmb) {
          e.preventDefault();
          copyToClipboard(`\\\\${ip}`);
          return;
        }

        if (isRdp) {
          e.preventDefault();
          const rdpContent = `full address:s:${ip}\nprompt for credentials:i:1\nscreen mode id:i:2\nauthentication level:i:2`;
          const blob = new Blob([rdpContent], { type: 'application/x-rdp' });
          const link = document.createElement('a');
          link.href = URL.createObjectURL(blob);
          link.download = `${ip}.rdp`;
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
          showToast('success', t('notifications.rdp_started'), t('notifications.rdp_generated', { ip }));
          return;
        }

        // For web protocols, open in new tab.
        if (url.startsWith('http')) {
          e.preventDefault();
          window.open(url, '_blank', 'noopener,noreferrer');
        } else {
          // For SSH/etc., trigger handler directly
          e.preventDefault();
          window.location.href = url;
        }
      }}
      title={isSmb ? `${t('notifications.click_to_copy')}: \\\\${ip}` : isRdp ? t('notifications.rdp_download', { ip }) : `${service.name} — ${url}`}
    >
      <div className={`service-badge__dot ${service.is_up ? 'service-badge__dot--up' : 'service-badge__dot--down'}`} />
      <Icon size={isMini ? 14 : 12} strokeWidth={2.5} />
      {(!isMini || isCopied) && <span>{isCopied ? t('notifications.copied') : service.name}</span>}
    </a>
  );
}
