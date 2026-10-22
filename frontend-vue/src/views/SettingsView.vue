<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { AlertTriangle, Check, FileText, Monitor, Moon, Sun } from 'lucide-vue-next';
import { api } from '@/api/client';
import PageHeader from '@/components/ui/PageHeader.vue';
import Button from '@/components/ui/Button.vue';
import Field from '@/components/ui/Field.vue';
import Input from '@/components/ui/Input.vue';
import Select from '@/components/ui/Select.vue';
import SettingsSection from '@/components/settings/SettingsSection.vue';
import UnitField from '@/components/settings/UnitField.vue';
import ActionRow from '@/components/settings/ActionRow.vue';
import SubnetsSection from '@/components/settings/SubnetsSection.vue';
import TelemetrySection from '@/components/settings/TelemetrySection.vue';
import GroupsSection from '@/components/settings/GroupsSection.vue';
import PasswordForm from '@/components/settings/PasswordForm.vue';
import TokensSection from '@/components/settings/TokensSection.vue';
import DataSections from '@/components/settings/DataSections.vue';
import LineColorsSection from '@/components/settings/LineColorsSection.vue';
import { useTheme, type ThemePreference } from '@/composables/useTheme';
import { locale, setLocale, t, type Locale } from '@/i18n';

/** Settings saved together through the save bar, keyed as the backend stores them (React useSettingsForm). */
const DEFAULT_FORM = {
  scan_interval: '0',
  quick_scan_interval: '300',
  scan_timeout: '1.5',
  'scanner.offline_threshold': '3',
  'dns.server': '',
  history_retention_days: '7',
  server_url_override: '',
  'system.log_level': 'info',
  'ui.start_page': '/',
};
type SettingsForm = typeof DEFAULT_FORM;
const KEYS = Object.keys(DEFAULT_FORM) as (keyof SettingsForm)[];

const form = ref<SettingsForm>({ ...DEFAULT_FORM });
const saved = ref<SettingsForm>({ ...DEFAULT_FORM });
const status = ref<'idle' | 'saving' | 'saved' | 'error'>('idle');
const { preference, setPreference } = useTheme();

function toForm(settings: Record<string, string>): SettingsForm {
  const next = { ...DEFAULT_FORM };
  for (const key of KEYS) if (settings[key]) next[key] = settings[key];
  return next;
}

async function load() {
  try {
    const loaded = toForm(await api.getSettings());
    form.value = { ...loaded };
    saved.value = loaded;
  } catch {
    // stays on defaults
  }
}
onMounted(load);

const isDirty = computed(() => KEYS.some((key) => form.value[key] !== saved.value[key]));

async function save() {
  status.value = 'saving';
  try {
    await api.updateSettings(form.value);
    localStorage.setItem('gravitylan_start_page', form.value['ui.start_page']);
    await load();
    status.value = 'saved';
    window.setTimeout(() => status.value === 'saved' && (status.value = 'idle'), 3000);
  } catch {
    status.value = 'error';
  }
}

function discard() {
  form.value = { ...saved.value };
  status.value = 'idle';
}

const sections = computed(() => [
  { id: 'scan', label: t('settings.section_scan') },
  { id: 'subnets', label: t('settings.subnets') },
  { id: 'system', label: t('settings.section_system') },
  { id: 'telemetry', label: t('telemetry_settings.title') },
  { id: 'groups', label: t('settings.manage_groups') },
  { id: 'appearance', label: t('gv.settings.appearance') },
  { id: 'access', label: t('settings.password.section') },
  { id: 'tokens', label: t('settings.api_tokens') },
  { id: 'backup', label: t('settings.backup_restore') },
  { id: 'danger', label: t('settings.danger_zone') },
]);

const themeOptions = computed<{ value: ThemePreference; label: string; icon: typeof Sun }[]>(() => [
  { value: 'system', label: t('gv.theme.system'), icon: Monitor },
  { value: 'light', label: t('gv.theme.light'), icon: Sun },
  { value: 'dark', label: t('gv.theme.dark'), icon: Moon },
]);
const languages: { value: Locale; key: string }[] = [
  { value: 'de', key: 'settings.language_de' },
  { value: 'en', key: 'settings.language_en' },
];
</script>

<template>
  <div class="mx-auto max-w-6xl px-4 py-5 pb-28 md:px-8 md:py-7">
    <PageHeader :title="t('sidebar.settings')" :description="t('settings.page_subtitle')" />

    <div class="mt-6 grid gap-6 lg:grid-cols-[13rem_1fr]">
      <!-- Section index: sticky on desktop, a scrollable strip on phones -->
      <nav :aria-label="t('gv.settings.sections')" class="-mx-4 overflow-x-auto px-4 [scrollbar-width:none] lg:sticky lg:top-6 lg:mx-0 lg:self-start lg:overflow-visible lg:px-0">
        <ul class="flex gap-1.5 lg:flex-col lg:gap-0.5">
          <li v-for="section in sections" :key="section.id" class="shrink-0">
            <a
              :href="`#${section.id}`"
              class="block rounded-md px-3 py-1.5 text-sm whitespace-nowrap transition-colors lg:py-2"
              :class="section.id === 'danger' ? 'text-danger-text hover:bg-danger/10' : 'border border-line text-fg-muted hover:bg-control-hover hover:text-fg lg:border-transparent'"
            >
              {{ section.label }}
            </a>
          </li>
        </ul>
      </nav>

      <div class="min-w-0 space-y-5">
        <SettingsSection id="scan" :title="t('settings.section_scan')" :description="t('settings.section_scan_desc')">
          <div class="grid gap-4 md:grid-cols-2">
            <UnitField v-model="form.scan_interval" :label="t('settings.scan_interval_label')" :hint="t('settings.scan_interval_hint')" :unit="t('settings.unit_minutes')" />
            <UnitField v-model="form.quick_scan_interval" :label="t('settings.quick_scan_label')" :hint="t('settings.quick_scan_hint')" :unit="t('settings.unit_seconds')" />
            <UnitField v-model="form.scan_timeout" :label="t('settings.scan_timeout_label')" :hint="t('settings.scan_timeout_desc')" :unit="t('settings.unit_seconds')" :step="0.1" />
            <UnitField v-model="form['scanner.offline_threshold']" :label="t('settings.offline_threshold_label')" :hint="t('settings.offline_threshold_hint')" :unit="t('settings.unit_checks')" />
            <Field v-slot="{ id, describedBy }" :label="t('settings.dns_custom_title')" :hint="t('settings.dns_custom_desc')">
              <Input :id="id" v-model="form['dns.server']" mono placeholder="192.168.1.1" :aria-describedby="describedBy" />
            </Field>
          </div>
        </SettingsSection>

        <SubnetsSection />

        <SettingsSection id="system" :title="t('settings.section_system')" :description="t('settings.section_system_desc')">
          <div class="grid gap-4 md:grid-cols-3">
            <UnitField v-model="form.history_retention_days" :label="t('settings.retention_label')" :hint="t('settings.retention_hint')" :unit="t('settings.unit_days')" />
            <Field v-slot="{ id, describedBy }" :label="t('settings.log_level')" :hint="t('settings.log_level_desc')">
              <Select
                :id="id"
                v-model="form['system.log_level']"
                :aria-describedby="describedBy"
                :options="[
                  { value: 'info', label: t('settings.log_level_info') },
                  { value: 'warning', label: t('settings.log_level_warning') },
                  { value: 'debug', label: t('settings.log_level_debug') },
                  { value: 'debug_sql', label: t('settings.log_level_sql') },
                ]"
              />
            </Field>
            <Field v-slot="{ id, describedBy }" :label="t('settings.start_page_label')" :hint="t('settings.start_page_hint')">
              <Select :id="id" v-model="form['ui.start_page']" :aria-describedby="describedBy" :options="[{ value: '/', label: t('settings.start_page_dashboard') }, { value: '/health', label: t('settings.start_page_health') }]" />
            </Field>
          </div>
          <Field v-slot="{ id, describedBy }" :label="t('settings.server_url_override')" :hint="t('settings.server_url_override_hint')">
            <Input :id="id" v-model="form.server_url_override" type="url" mono placeholder="http://192.168.1.10:8000" :aria-describedby="describedBy" />
          </Field>
          <ActionRow :title="t('settings.system_livelogs')" :description="t('settings.system_livelogs_desc')">
            <RouterLink to="/logs" class="inline-flex h-8 items-center gap-1.5 rounded-md border border-line bg-control px-2.5 text-xs font-medium text-fg hover:border-line-strong hover:bg-control-hover">
              <FileText class="size-4" aria-hidden="true" />{{ t('settings.system_livelogs_open') }}
            </RouterLink>
          </ActionRow>
        </SettingsSection>

        <TelemetrySection />
        <GroupsSection />

        <SettingsSection id="appearance" :title="t('gv.settings.appearance')" :description="t('settings.section_language_desc')">
          <div class="grid gap-4 sm:grid-cols-2">
            <fieldset>
              <legend class="mb-1.5 text-xs font-medium text-fg">{{ t('settings.language') }}</legend>
              <div class="flex rounded-md border border-line bg-sunken p-0.5">
                <button
                  v-for="lang in languages"
                  :key="lang.value"
                  type="button"
                  :lang="lang.value"
                  :aria-pressed="locale === lang.value"
                  class="h-8 flex-1 rounded-[5px] text-sm transition-colors"
                  :class="locale === lang.value ? 'bg-control font-medium text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
                  @click="setLocale(lang.value)"
                >
                  {{ t(lang.key) }}
                </button>
              </div>
            </fieldset>
            <fieldset>
              <legend class="mb-1.5 text-xs font-medium text-fg">{{ t('gv.theme.label') }}</legend>
              <div class="flex rounded-md border border-line bg-sunken p-0.5">
                <button
                  v-for="opt in themeOptions"
                  :key="opt.value"
                  type="button"
                  :aria-pressed="preference === opt.value"
                  class="flex h-8 flex-1 items-center justify-center gap-1.5 rounded-[5px] text-sm transition-colors"
                  :class="preference === opt.value ? 'bg-control font-medium text-fg shadow-sm' : 'text-fg-subtle hover:text-fg'"
                  @click="setPreference(opt.value)"
                >
                  <component :is="opt.icon" class="size-4" aria-hidden="true" />{{ opt.label }}
                </button>
              </div>
            </fieldset>
          </div>
          <LineColorsSection />
        </SettingsSection>

        <SettingsSection id="access" :title="t('settings.password.section')" :description="t('settings.password.section_desc')">
          <PasswordForm />
        </SettingsSection>

        <TokensSection />
        <DataSections />
      </div>
    </div>

    <!-- Save bar for the scan/system fields: visible while there is something to save or report -->
    <Transition name="gl-savebar">
      <div
        v-if="isDirty || status !== 'idle'"
        role="region"
        :aria-label="t('settings.unsaved_changes')"
        class="fixed inset-x-3 bottom-[calc(4.5rem+env(safe-area-inset-bottom))] z-30 mx-auto flex max-w-2xl items-center gap-3 rounded-lg border border-line-strong bg-surface px-4 py-3 shadow-pop md:bottom-5 md:left-[calc(15rem+1.5rem)]"
      >
        <span role="status" class="flex min-w-0 flex-1 items-center gap-2 text-sm">
          <template v-if="status === 'saved'"><Check class="size-4 text-accent-text" aria-hidden="true" />{{ t('settings.save_success') }}</template>
          <template v-else-if="status === 'error'"><AlertTriangle class="size-4 text-danger-text" aria-hidden="true" />{{ t('settings.save_error') }}</template>
          <template v-else><span class="size-2 rounded-full bg-warn" aria-hidden="true" />{{ t('settings.unsaved_changes') }}</template>
        </span>
        <template v-if="isDirty">
          <Button size="sm" variant="ghost" :disabled="status === 'saving'" @click="discard">{{ t('settings.discard') }}</Button>
          <Button size="sm" variant="primary" :loading="status === 'saving'" @click="save"><Check v-if="status !== 'saving'" aria-hidden="true" />{{ t('common.save') }}</Button>
        </template>
      </div>
    </Transition>
  </div>
</template>

<style>
.gl-savebar-enter-active {
  transition: opacity 200ms ease-out, transform 280ms var(--ease-out-expo);
}
.gl-savebar-leave-active {
  transition: opacity 150ms ease-in;
}
.gl-savebar-enter-from {
  opacity: 0;
  transform: translateY(12px);
}
.gl-savebar-leave-to {
  opacity: 0;
}
</style>
