/** Light/dark theme for GravityUI. The preference survives reloads; "system" follows the OS. */
import { computed, ref, watch } from 'vue';

export type ThemePreference = 'system' | 'light' | 'dark';

const STORAGE_KEY = 'gravityui.theme';
const media = typeof window !== 'undefined' ? window.matchMedia('(prefers-color-scheme: light)') : null;

function readPreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === 'light' || stored === 'dark' ? stored : 'system';
  } catch {
    return 'system';
  }
}

const preference = ref<ThemePreference>(readPreference());
const systemLight = ref(media?.matches ?? false);
media?.addEventListener('change', (event) => {
  systemLight.value = event.matches;
});

const resolved = computed<'light' | 'dark'>(() =>
  preference.value === 'system' ? (systemLight.value ? 'light' : 'dark') : preference.value,
);

function apply(theme: 'light' | 'dark') {
  const root = document.documentElement;
  root.setAttribute('data-theme', theme);
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#0e0e11' : '#ffffff');
}

watch(resolved, apply, { immediate: true });

export function useTheme() {
  function setPreference(next: ThemePreference) {
    preference.value = next;
    try {
      if (next === 'system') localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Private mode: the choice simply lasts for this page view
    }
  }

  /** system -> light -> dark -> system */
  function cycle() {
    setPreference(preference.value === 'system' ? 'light' : preference.value === 'light' ? 'dark' : 'system');
  }

  return { preference, resolved, setPreference, cycle };
}
