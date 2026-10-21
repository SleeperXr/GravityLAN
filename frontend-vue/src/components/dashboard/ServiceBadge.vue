<script setup lang="ts">
import { computed, ref, type Component } from 'vue';
import {
  Activity,
  ArrowRightLeft,
  Check,
  Cpu,
  Database,
  ExternalLink,
  Folder,
  Globe,
  Lock,
  Monitor,
  Server,
  Settings,
  Shield,
  Terminal,
} from 'lucide-vue-next';
import type { Service } from '@/types';
import { copyText } from '@/lib/clipboard';
import { useToast } from '@/composables/useToast';
import { t } from '@/i18n';

/**
 * One service of a device, one click away: web UIs open in a new tab, SMB copies the
 * UNC path, RDP downloads a .rdp file, everything else hands the URL to the OS.
 */
const props = defineProps<{ service: Service; ip: string; disabled?: boolean }>();
const { showToast } = useToast();
const copied = ref(false);

const ICON_MAP: Record<string, Component> = {
  ssh: Terminal,
  http: Globe,
  https: Lock,
  rdp: Monitor,
  smb: Folder,
  scp: ArrowRightLeft,
  proxmox: Server,
  esxi: Cpu,
  synology: Database,
  sophos_admin: Shield,
  securepoint: Shield,
  cockpit: Activity,
  webmin: Settings,
  home_assistant: Globe,
};

const icon = computed<Component>(() => {
  const protocol = props.service.protocol.toLowerCase();
  const name = props.service.name.toLowerCase();
  if (ICON_MAP[protocol]) return ICON_MAP[protocol];
  const key = Object.keys(ICON_MAP).find((k) => name.includes(k));
  return key ? ICON_MAP[key] : ExternalLink;
});

const url = computed(() => props.service.url_template.replace('{ip}', props.ip).replace('{port}', String(props.service.port)));
const protocol = computed(() => props.service.protocol.toLowerCase());
const unc = computed(() => `\\\\${props.ip}`);

const title = computed(() => {
  if (protocol.value === 'smb') return `${t('notifications.click_to_copy')}: ${unc.value}`;
  if (protocol.value === 'rdp') return t('notifications.rdp_download', { ip: props.ip });
  return `${props.service.name} — ${url.value}`;
});

async function onClick(event: MouseEvent) {
  event.stopPropagation();
  if (props.disabled) {
    event.preventDefault();
    return;
  }
  if (protocol.value === 'smb') {
    event.preventDefault();
    if (await copyText(unc.value)) {
      copied.value = true;
      window.setTimeout(() => (copied.value = false), 2000);
      showToast('info', t('notifications.copied'), unc.value);
    } else {
      showToast('error', t('common.error'), t('settings.copy_failed'));
    }
    return;
  }
  if (protocol.value === 'rdp') {
    event.preventDefault();
    const content = `full address:s:${props.ip}\nprompt for credentials:i:1\nscreen mode id:i:2\nauthentication level:i:2`;
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([content], { type: 'application/x-rdp' }));
    link.download = `${props.ip}.rdp`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    showToast('success', t('notifications.rdp_started'), t('notifications.rdp_generated', { ip: props.ip }));
    return;
  }
  if (!url.value.startsWith('http')) {
    // ssh:// and friends: let the OS pick the handler
    event.preventDefault();
    window.location.href = url.value;
  }
}
</script>

<template>
  <a
    :href="protocol === 'smb' || protocol === 'rdp' ? '#' : url"
    :target="url.startsWith('http') ? '_blank' : undefined"
    rel="noopener noreferrer"
    :title="title"
    :aria-disabled="disabled || undefined"
    class="group/svc inline-flex h-7 max-w-full min-w-0 items-center gap-1.5 rounded-md border border-line bg-raised px-2 text-xs font-medium text-fg-muted transition-colors"
    :class="[
      disabled ? 'pointer-events-none opacity-60' : 'hover:border-line-strong hover:bg-control-hover hover:text-fg',
      !service.is_up && 'border-dashed',
    ]"
    @click="onClick"
  >
    <span
      class="size-1.5 shrink-0 rounded-full"
      :class="service.is_up ? 'bg-accent' : 'bg-danger'"
      role="img"
      :aria-label="service.is_up ? t('network.online') : t('network.offline')"
    />
    <component :is="copied ? Check : icon" class="size-3.5 shrink-0" aria-hidden="true" />
    <span class="truncate" :class="!service.is_up && 'line-through decoration-danger/50'">{{ copied ? t('notifications.copied') : service.name }}</span>
  </a>
</template>
