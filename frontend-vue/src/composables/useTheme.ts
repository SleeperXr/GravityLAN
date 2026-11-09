/**
 * Colour theme for GravityUI. Dark (night network) is the default, aurora is its more colourful
 * sibling; "system" follows the OS between light and dark.
 */
import { computed, ref, watch } from 'vue';

export type ThemePreference = 'system' | 'light' | 'dark' | 'aurora';
export type ResolvedTheme = Exclude<ThemePreference, 'system'>;

const STORAGE_KEY = 'gravityui.theme';
const media = typeof window !== 'undefined' ? window.matchMedia('(prefers-color-scheme: light)') : null;

/** Browser bar colour per theme: the theme's --gl-canvas (white for the daytime map) */
const BROWSER_BAR: Record<ResolvedTheme, string> = { dark: '#0c0f14', light: '#ffffff', aurora: '#08090d' };

function readPreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === 'light' || stored === 'system' || stored === 'aurora' ? stored : 'dark';
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
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', BROWSER_BAR[theme]);
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

  /** dark -> aurora -> light -> system -> dark */
  function cycle() {
    const order: ThemePreference[] = ['dark', 'aurora', 'light', 'system'];
    setPreference(order[(order.indexOf(preference.value) + 1) % order.length]);
  }

  return { preference, resolved, setPreference, cycle };
}
