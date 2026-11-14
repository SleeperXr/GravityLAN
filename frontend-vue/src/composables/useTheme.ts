/**
 * Colour theme for GravityUI. Dark (night network) is the default; the built-in designs are
 * listed in lib/themes.ts, uploaded ones in lib/customThemes.ts. "system" follows the OS between
 * light and dark.
 */
import { computed, ref, watch } from 'vue';
import { THEMES, isThemeId, themeInfo, type ThemeId } from '@/lib/themes';
import { applyCustomColors, customThemes, findCustomTheme, type CustomTheme } from '@/lib/customThemes';

export type CustomPreference = `custom:${string}`;
export type ThemePreference = 'system' | ThemeId | CustomPreference;
/** The built-in design whose block applies: an uploaded design resolves to its base */
export type ResolvedTheme = ThemeId;

const STORAGE_KEY = 'gravityui.theme';
const media = typeof window !== 'undefined' ? window.matchMedia('(prefers-color-scheme: light)') : null;

export function isCustomPreference(value: unknown): value is CustomPreference {
  return typeof value === 'string' && value.startsWith('custom:');
}

function readPreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'paper') return 'light'; // the Day map was "paper" in a test build
    if (isCustomPreference(stored)) return findCustomTheme(stored.slice(7)) ? stored : 'dark';
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

/** The uploaded design in use, if any (gone from the list: none) */
const activeCustom = computed<CustomTheme | null>(() =>
  isCustomPreference(preference.value) ? (customThemes.value.find((t) => t.id === preference.value.slice(7)) ?? null) : null,
);

const resolved = computed<ResolvedTheme>(() => {
  if (activeCustom.value) return activeCustom.value.base;
  if (preference.value === 'system' || isCustomPreference(preference.value)) return systemLight.value ? 'light' : 'dark';
  return preference.value;
});

/** Changes whenever the colours on screen do, also between an uploaded design and its base */
const appliedKey = computed(() => (activeCustom.value ? `custom:${activeCustom.value.id}` : resolved.value));

function apply() {
  const root = document.documentElement;
  root.setAttribute('data-theme', resolved.value);
  applyCustomColors(activeCustom.value?.colors ?? null, root);
  const bar = activeCustom.value?.colors.canvas ?? themeInfo(resolved.value).browserBar;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', bar);
}

watch([resolved, activeCustom], apply, { immediate: true });

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

  /** Every built-in design in menu order, then "system", then round again */
  function cycle() {
    const order: ThemePreference[] = [...THEMES.map((t) => t.id), 'system'];
    const index = order.indexOf(preference.value);
    setPreference(order[(index + 1) % order.length]);
  }

  return { preference, resolved, activeCustom, appliedKey, setPreference, cycle };
}
