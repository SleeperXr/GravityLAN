import { defineStore } from 'pinia';
import { ref } from 'vue';
import { api } from '@/api/client';

const SETTING_KEY = 'ui.line_colors';
const ORBIT_KEY = 'ui.orbit_layout';
const HEX = /^#[0-9a-f]{6}$/i;

/**
 * User-chosen line colours per subnet (setting `ui.line_colors`, JSON {subnetId: "#rrggbb"}).
 * Without an entry a subnet takes its palette colour (--line-N), which follows light/dark.
 */
export const useAppearance = defineStore('appearance', () => {
  const lineColors = ref<Record<string, string>>({});
  /**
   * The orbit map shows the user's own arrangement (`ui.orbit_layout = custom`) once they moved
   * or arranged something there; until then it lays itself out, ignoring positions saved by the
   * React topology or the earlier transit map.
   */
  const orbitCustom = ref(false);
  let loaded: Promise<void> | null = null;

  function load() {
    loaded ??= (async () => {
      try {
        const settings = await api.getSettings();
        const raw = settings[SETTING_KEY];
        const parsed = raw ? (JSON.parse(raw) as Record<string, string>) : {};
        lineColors.value = Object.fromEntries(Object.entries(parsed).filter(([, v]) => HEX.test(v)));
        orbitCustom.value = settings[ORBIT_KEY] === 'custom';
      } catch {
        lineColors.value = {};
      }
    })();
    return loaded;
  }

  async function setOrbitCustom(custom: boolean) {
    orbitCustom.value = custom;
    await api.updateSettings({ [ORBIT_KEY]: custom ? 'custom' : '' });
  }

  async function setLineColor(subnetId: number, color: string | null) {
    const next = { ...lineColors.value };
    if (color && HEX.test(color)) next[String(subnetId)] = color;
    else delete next[String(subnetId)];
    lineColors.value = next;
    await api.updateSettings({ [SETTING_KEY]: JSON.stringify(next) });
  }

  return { lineColors, orbitCustom, load, setLineColor, setOrbitCustom };
});
