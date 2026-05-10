import { useEffect } from 'react';
import { api } from '../api/client';

export function ThemeManager() {

  useEffect(() => {
    const lastThemeRef = { current: '' };

    const applyTheme = async () => {
      try {
        const theme = await api.getThemeSettings();
        const themeStr = JSON.stringify(theme);
        if (themeStr === lastThemeRef.current) return; // Skip if identical
        lastThemeRef.current = themeStr;

        console.log('Applying theme settings...', theme);
        const root = document.documentElement;

        if (theme['theme.primary_color']) {
          root.style.setProperty('--accent-primary', theme['theme.primary_color']);
        }
        
        if (theme['theme.border_radius']) {
          const radius = theme['theme.border_radius'];
          root.style.setProperty('--radius-md', radius);
          root.style.setProperty('--radius-lg', `calc(${radius} * 1.5)`);
          root.style.setProperty('--radius-xl', `calc(${radius} * 2.5)`);
        }
        
        // Glass Mode logic
        const isGlass = theme['theme.glass_mode'] === 'true';
        if (isGlass) {
          root.style.setProperty('--bg-card', 'rgba(30, 41, 59, 0.6)');
          root.style.setProperty('--bg-surface', 'rgba(15, 23, 42, 0.8)');
          root.classList.add('glass-mode');
        } else {
          root.classList.remove('glass-mode');
          // Reset to defaults if glass disabled
          root.style.removeProperty('--bg-card');
          root.style.removeProperty('--bg-surface');
        }

        if (theme['theme.bg_style'] && theme['theme.bg_style'] !== 'default') {
          const newClass = `theme-${theme['theme.bg_style']}`;
          if (document.body.className !== newClass) {
            document.body.className = newClass;
          }
        } else if (document.body.className.startsWith('theme-')) {
          document.body.className = '';
        }

      } catch (err) {
        console.warn('Theme settings sync error (ignoring):', err);
      }
    };

    applyTheme();
    
    // Refresh theme ONLY on window focus to minimize background noise
    window.addEventListener('focus', applyTheme);
    return () => window.removeEventListener('focus', applyTheme);
  }, []);

  return null; // This component only manages side effects
}
