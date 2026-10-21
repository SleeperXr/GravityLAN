/** Promise-based confirm dialog, rendered once by ConfirmHost.vue (replaces window.confirm). */
import { ref } from 'vue';

export interface ConfirmOptions {
  title: string;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Destructive action: red confirm button */
  danger?: boolean;
}

interface PendingConfirm extends ConfirmOptions {
  resolve: (ok: boolean) => void;
}

export const pendingConfirm = ref<PendingConfirm | null>(null);

export function confirmAction(options: ConfirmOptions): Promise<boolean> {
  pendingConfirm.value?.resolve(false);
  return new Promise((resolve) => {
    pendingConfirm.value = { ...options, resolve };
  });
}

export function settleConfirm(ok: boolean) {
  pendingConfirm.value?.resolve(ok);
  pendingConfirm.value = null;
}

export function useConfirm() {
  return { confirm: confirmAction };
}
