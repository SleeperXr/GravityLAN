/**
 * Colour theme for GravityUI. Dark (night network) is the default; the designs themselves are
 * listed in lib/themes.ts. "system" follows the OS between light and dark.
 */
import { computed, ref, watch } from 'vue';
import { THEMES, isThemeId, themeInfo, type ThemeId } from '@/lib/themes';

export type ThemePreference = 'system' | ThemeId;
export type ResolvedTheme = ThemeId;

const STORAGE_KEY = 'gravityui.theme';
const media = typeof window !== 'undefined' ? window.matchMedia('(prefers-color-scheme: light)') : null;

function readPreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'paper') return 'light'; // the Day map was "paper" in a test build
    return stored === 'system' || isThemeId(stored) ? stored : 'dark';
  } catch {
    return 'dark';
  }
}

const preference = ref<ThemePreference>(readPreference());
const systemLight = ref(media?.matches ?? false);
media?.addEventListener('change', (event) => {
  systemLight.value = event.matches;
});

const resolved = computed<ResolvedTheme>(() =>
  preference.value === 'system' ? (systemLight.value ? 'light' : 'dark') : preference.value,
);

function apply(theme: ResolvedTheme) {
  const root = document.documentElement;
  root.setAttribute('data-theme', theme);
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', themeInfo(theme).browserBar);
}

watch(resolved, apply, { immediate: true });

export function useTheme() {
  function setPreference(next: ThemePreference) {
    preference.value = next;
    try {
      if (next === 'dark') localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Private mode: the choice simply lasts for this page view
    }
  }

  /** Every design in menu order, then "system", then round again */
  function cycle() {
    const order: ThemePreference[] = [...THEMES.map((t) => t.id), 'system'];
    setPreference(order[(order.indexOf(preference.value) + 1) % order.length]);
  }

  return { preference, resolved, setPreference, cycle };
}
