<script setup lang="ts">
import { computed, ref } from 'vue';
import { CheckCircle2, KeyRound } from 'lucide-vue-next';
import { api } from '@/api/client';
import Button from '@/components/ui/Button.vue';
import Field from '@/components/ui/Field.vue';
import Input from '@/components/ui/Input.vue';
import { t } from '@/i18n';

/** Change the admin password; the server signs out every other session. */
const MIN_LENGTH = 8;
const current = ref('');
const next = ref('');
const repeat = ref('');
const busy = ref(false);
const error = ref<string | null>(null);
const done = ref<number | null>(null);

const tooShort = computed(() => next.value.length > 0 && next.value.length < MIN_LENGTH);
const mismatch = computed(() => repeat.value.length > 0 && next.value !== repeat.value);

async function submit() {
  error.value = null;
  done.value = null;
  if (next.value.length < MIN_LENGTH) return void (error.value = t('settings.password.too_short', { count: MIN_LENGTH }));
  if (next.value !== repeat.value) return void (error.value = t('settings.password.mismatch'));
  busy.value = true;
  try {
    const res = await api.changePassword(current.value, next.value);
    done.value = res.other_sessions_ended;
    current.value = next.value = repeat.value = '';
  } catch (err) {
    const message = (err as Error).message;
    // The server answers in English; show the known cases in the UI language
    if (/current password is wrong/i.test(message)) error.value = t('settings.password.wrong_current');
    else if (/differs from the current/i.test(message)) error.value = t('settings.password.same_as_current');
    else error.value = message;
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <form class="space-y-4" autocomplete="on" @submit.prevent="submit">
    <!-- Lets password managers attach the new password to the right account -->
    <input type="text" name="username" autocomplete="username" value="admin" readonly hidden />
    <div class="grid gap-4 md:grid-cols-3">
      <Field v-slot="{ id }" :label="t('settings.password.current')">
        <Input :id="id" v-model="current" type="password" autocomplete="current-password" required />
      </Field>
      <Field v-slot="{ id, describedBy }" :label="t('settings.password.new')" :hint="t('settings.password.hint', { count: MIN_LENGTH })" :error="tooShort ? t('settings.password.too_short', { count: MIN_LENGTH }) : null">
        <Input :id="id" v-model="next" type="password" autocomplete="new-password" :minlength="MIN_LENGTH" required :invalid="tooShort" :aria-describedby="describedBy" />
      </Field>
      <Field v-slot="{ id, describedBy }" :label="t('settings.password.repeat')" :error="mismatch ? t('settings.password.mismatch') : null">
        <Input :id="id" v-model="repeat" type="password" autocomplete="new-password" required :invalid="mismatch" :aria-describedby="describedBy" />
      </Field>
    </div>
    <p v-if="error && !tooShort && !mismatch" role="alert" class="text-sm text-danger-text">{{ error }}</p>
    <div v-if="done !== null" role="status" class="flex gap-2.5 rounded-md border border-accent/30 bg-accent/[0.07] p-3 text-sm">
      <CheckCircle2 class="mt-0.5 size-4 shrink-0 text-accent-text" aria-hidden="true" />
      <div>
        <p class="text-fg">{{ t('settings.password.changed') }}</p>
        <p v-if="done > 0" class="mt-0.5 text-xs text-fg-muted">{{ t('settings.password.others_logged_out', { count: done }) }}</p>
      </div>
    </div>
    <Button type="submit" :loading="busy" :disabled="!current || !next || !repeat"><KeyRound v-if="!busy" aria-hidden="true" />{{ t('settings.password.submit') }}</Button>
  </form>
</template>
