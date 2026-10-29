<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { Check, Pencil, Plus, Trash2, X } from 'lucide-vue-next';
import { api } from '@/api/client';
import type { DeviceGroup } from '@/types';
import SettingsSection from './SettingsSection.vue';
import Button from '@/components/ui/Button.vue';
import Badge from '@/components/ui/Badge.vue';
import Input from '@/components/ui/Input.vue';
import { useToast } from '@/composables/useToast';
import { useConfirm } from '@/composables/useConfirm';
import { useNetworkStore } from '@/stores/network';
import { t } from '@/i18n';

const { showToast } = useToast();
const { confirm } = useConfirm();
const store = useNetworkStore();
const groups = ref<DeviceGroup[]>([]);
const newName = ref('');
const editingId = ref<number | null>(null);
const editingName = ref('');

async function load() {
  try {
    groups.value = [...(await api.getGroups())].sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0));
  } catch {
    // keep the list
  }
}
onMounted(load);

const failed = (err: unknown) => showToast('error', t('common.error'), `${t('settings.group_failed')} ${(err as Error).message}`);

async function create() {
  const name = newName.value.trim();
  if (!name) return;
  try {
    await api.createGroup({ name, icon: 'folder' });
    newName.value = '';
    await load();
    void store.loadData(true);
  } catch (err) {
    failed(err);
  }
}

function startEdit(group: DeviceGroup) {
  editingId.value = group.id;
  editingName.value = group.name;
}

async function saveRename(group: DeviceGroup) {
  const name = editingName.value.trim();
  if (!name || name === group.name) {
    editingId.value = null;
    return;
  }
  try {
    await api.updateGroup(group.id, { name });
    showToast('success', t('notifications.saved'), t('settings.group_renamed'));
    editingId.value = null;
    await load();
    void store.loadData(true);
  } catch (err) {
    failed(err);
  }
}

async function remove(group: DeviceGroup) {
  const ok = await confirm({ title: t('settings.delete_group', { name: group.name }), message: t('settings.delete_group_confirm'), danger: true, confirmLabel: t('common.delete') });
  if (!ok) return;
  try {
    await api.deleteGroup(group.id);
    await load();
    void store.loadData(true);
  } catch (err) {
    failed(err);
  }
}
</script>

<template>
  <SettingsSection id="groups" :title="t('settings.manage_groups')" :description="t('settings.section_groups_desc')">
    <form class="flex gap-2" @submit.prevent="create">
      <Input v-model="newName" :placeholder="t('settings.new_group_name')" :aria-label="t('settings.new_group_name')" maxlength="100" />
      <Button type="submit" :disabled="!newName.trim()"><Plus aria-hidden="true" />{{ t('settings.create') }}</Button>
    </form>
    <!-- Ruled rows, not a box: the section card is the only frame -->
    <ul class="divide-y divide-line border-y border-line">
      <li v-for="group in groups" :key="group.id" class="flex min-h-12 items-center gap-2 py-2">
        <form v-if="editingId === group.id" class="flex flex-1 items-center gap-2" @submit.prevent="saveRename(group)">
          <Input v-model="editingName" class="h-8" maxlength="100" autofocus :aria-label="t('settings.edit_group', { name: group.name })" @keydown.esc="editingId = null" />
          <Button type="submit" size="icon-sm" variant="ghost" :disabled="!editingName.trim() || editingName.trim() === group.name" :aria-label="t('common.save')"><Check aria-hidden="true" /></Button>
          <Button size="icon-sm" variant="ghost" :aria-label="t('common.cancel')" @click="editingId = null"><X aria-hidden="true" /></Button>
        </form>
        <template v-else>
          <span class="min-w-0 flex-1 truncate text-sm text-fg">{{ group.name }}</span>
          <span class="font-mono text-xs text-fg-subtle tabular">{{ group.device_count }}</span>
          <Badge v-if="group.is_default">{{ t('settings.standard') }}</Badge>
          <Button size="icon-sm" variant="ghost" :aria-label="t('settings.edit_group', { name: group.name })" :title="t('settings.rename_group')" @click="startEdit(group)"><Pencil aria-hidden="true" /></Button>
          <Button v-if="!group.is_default" size="icon-sm" variant="danger-ghost" :aria-label="t('settings.delete_group', { name: group.name })" @click="remove(group)"><Trash2 aria-hidden="true" /></Button>
        </template>
      </li>
    </ul>
  </SettingsSection>
</template>
