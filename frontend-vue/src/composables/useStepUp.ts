/**
 * Password confirmation before sensitive actions (AP-12), rendered once by StepUpHost.vue.
 * The API client calls requestStepUp() when the server answers 403 with X-Step-Up, and repeats the
 * request once the user confirmed; cancelling resolves false and the request fails as before.
 */
import { ref } from 'vue';

export type StepUpScope = 'remote' | 'credentials' | 'instance';

interface PendingStepUp {
  scope: StepUpScope;
  resolve: (ok: boolean) => void;
}

export const pendingStepUp = ref<PendingStepUp | null>(null);
// Several requests may need the same confirmation at once: they share one dialog
let inflight: Promise<boolean> | null = null;

export function requestStepUp(scope: string): Promise<boolean> {
  if (inflight) return inflight;
  const known: StepUpScope = scope === 'credentials' || scope === 'instance' ? scope : 'remote';
  inflight = new Promise<boolean>((resolve) => {
    pendingStepUp.value = { scope: known, resolve };
  }).finally(() => {
    inflight = null;
  });
  return inflight;
}

export function settleStepUp(ok: boolean) {
  pendingStepUp.value?.resolve(ok);
  pendingStepUp.value = null;
}
