import { useState, useEffect } from 'react';
import { api } from '../api/client';

export function ThemeManager() {

  useEffect(() => {
    const applyTheme = async () => {
      try {
        console.log('Applying theme settings...');
        const theme = await api.getThemeSettings();
        const root = document.documentElement;

        if (theme['theme.primary_color']) {
          root.style.setProperty('--accent-primary', theme['theme.primary_color']);
          root.style.setProperty('--accent-secondary', '#6366f1');
        }
        if (theme['theme.border_radius']) {
          root.style.setProperty('--radius-md', theme['theme.border_radius']);
          root.style.setProperty('--radius-lg', `calc(${theme['theme.border_radius']} * 1.5)`);
          root.style.setProperty('--radius-xl', `calc(${theme['theme.border_radius']} * 2.5)`);
        }
        
        // Glass Mode logic
        if (theme['theme.glass_mode'] === 'true') {
          root.style.setProperty('--bg-card', 'rgba(30, 41, 59, 0.6)');
          root.style.setProperty('--bg-surface', 'rgba(15, 23, 42, 0.8)');
          root.classList.add('glass-mode');
        } else {
          root.classList.remove('glass-mode');
        }

        if (theme['theme.bg_style'] && theme['theme.bg_style'] !== 'default') {
          document.body.className = `theme-${theme['theme.bg_style']}`;
        }

      } catch (err) {
        console.warn('Theme settings not yet available, using defaults.');
      } finally {
        // Theme applied
      }
    };

    applyTheme();
    
    // Refresh theme when window gains focus (optional but helpful)
    window.addEventListener('focus', applyTheme);
    return () => window.removeEventListener('focus', applyTheme);
  }, []);

  return null; // This component only manages side effects
}
