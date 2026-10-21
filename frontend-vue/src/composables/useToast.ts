/** Toasts with the same shape as the React ToastContext, plus a history for the notification center. */
import { readonly, ref } from 'vue';

export type ToastType = 'success' | 'error' | 'info';

export interface Toast {
  id: number;
  type: ToastType;
  title: string;
  message: string;
  timestamp: Date;
}

const toasts = ref<Toast[]>([]);
const history = ref<Toast[]>([]);
let nextId = 1;

function removeToast(id: number) {
  toasts.value = toasts.value.filter((toast) => toast.id !== id);
}

function showToast(type: ToastType, title: string, message = '') {
  const toast: Toast = { id: nextId++, type, title, message, timestamp: new Date() };
  toasts.value = [...toasts.value.slice(-3), toast];
  history.value = [toast, ...history.value].slice(0, 50);
  // Errors stay long enough to be read and copied
  window.setTimeout(() => removeToast(toast.id), type === 'error' ? 15000 : 5000);
}

function clearHistory() {
  history.value = [];
}

export function useToast() {
  return { toasts: readonly(toasts), history: readonly(history), showToast, removeToast, clearHistory };
}
