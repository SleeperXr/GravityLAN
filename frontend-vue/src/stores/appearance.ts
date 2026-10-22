import { defineStore } from 'pinia';
import { ref } from 'vue';
import { api } from '@/api/client';

const SETTING_KEY = 'ui.line_colors';
const HEX = /^#[0-9a-f]{6}$/i;

/**
 * User-chosen line colours per subnet (setting `ui.line_colors`, JSON {subnetId: "#rrggbb"}).
 * Without an entry a subnet takes its palette colour (--line-N), which follows light/dark.
 */
export const useAppearance = defineStore('appearance', () => {
  const lineColors = ref<Record<string, string>>({});
  let loaded = false;

  async function load() {
    if (loaded) return;
    loaded = true;
    try {
      const raw = (await api.getSettings())[SETTING_KEY];
      const parsed = raw ? (JSON.parse(raw) as Record<string, string>) : {};
      lineColors.value = Object.fromEntries(Object.entries(parsed).filter(([, v]) => HEX.test(v)));
    } catch {
      lineColors.value = {};
    }
  }

  async function setLineColor(subnetId: number, color: string | null) {
    const next = { ...lineColors.value };
    if (color && HEX.test(color)) next[String(subnetId)] = color;
    else delete next[String(subnetId)];
    lineColors.value = next;
    await api.updateSettings({ [SETTING_KEY]: JSON.stringify(next) });
  }

  return { lineColors, load, setLineColor };
});
