import { defineStore } from 'pinia';
import { ref } from 'vue';
import { api } from '@/api/client';
import type { OrbitRole, OrbitRoles } from '@/components/orbit/orbitModel';

const SETTING_KEY = 'ui.line_colors';
const ORBIT_KEY = 'ui.orbit_layout';
const ROLES_KEY = 'ui.orbit_roles';
const LINK_TYPE_KEY = 'ui.link_type_colors';
const ROLES: OrbitRole[] = ['star', 'planet', 'dwarf', 'moon'];
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
  /** Orbit roles the user chose per device (`ui.orbit_roles`, JSON {deviceId: role}) */
  const orbitRoles = ref<OrbitRoles>({});
  /** Beam colour per connection type (`ui.link_type_colors`, JSON {"10GbE": "#rrggbb"}); a link's own colour wins */
  const linkTypeColors = ref<Record<string, string>>({});
  let loaded: Promise<void> | null = null;

  function load() {
    loaded ??= (async () => {
      try {
        const settings = await api.getSettings();
        const raw = settings[SETTING_KEY];
        const parsed = raw ? (JSON.parse(raw) as Record<string, string>) : {};
        lineColors.value = Object.fromEntries(Object.entries(parsed).filter(([, v]) => HEX.test(v)));
        orbitCustom.value = settings[ORBIT_KEY] === 'custom';
        const roles = settings[ROLES_KEY] ? (JSON.parse(settings[ROLES_KEY]) as Record<string, string>) : {};
        const types = settings[LINK_TYPE_KEY] ? (JSON.parse(settings[LINK_TYPE_KEY]) as Record<string, string>) : {};
        linkTypeColors.value = Object.fromEntries(Object.entries(types).filter(([, v]) => HEX.test(v)));
        orbitRoles.value = Object.fromEntries(Object.entries(roles).filter(([, r]) => ROLES.includes(r as OrbitRole))) as OrbitRoles;
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

  /** Pin a device's orbit role, or hand it back to automatic with null. */
  async function setOrbitRole(deviceId: number, role: OrbitRole | null) {
    const next = { ...orbitRoles.value };
    if (role) next[String(deviceId)] = role;
    else delete next[String(deviceId)];
    orbitRoles.value = next;
    await api.updateSettings({ [ROLES_KEY]: JSON.stringify(next) });
  }

  async function setLinkTypeColor(type: string, color: string | null) {
    const next = { ...linkTypeColors.value };
    if (color && HEX.test(color)) next[type] = color;
    else delete next[type];
    linkTypeColors.value = next;
    await api.updateSettings({ [LINK_TYPE_KEY]: JSON.stringify(next) });
  }

  async function setLineColor(subnetId: number, color: string | null) {
    const next = { ...lineColors.value };
    if (color && HEX.test(color)) next[String(subnetId)] = color;
    else delete next[String(subnetId)];
    lineColors.value = next;
    await api.updateSettings({ [SETTING_KEY]: JSON.stringify(next) });
  }

  return { lineColors, linkTypeColors, orbitCustom, orbitRoles, load, setLineColor, setLinkTypeColor, setOrbitCustom, setOrbitRole };
});
