/** Toasts with the same shape as the React ToastContext, plus a history for the notification center. */
import { readonly, ref } from 'vue';

export type ToastType = 'success' | 'error' | 'info';

/** A button in the toast, e.g. Undo; the toast closes when it is used. */
export interface ToastAction {
  label: string;
  run: () => void;
}

export interface Toast {
  id: number;
  type: ToastType;
  title: string;
  message: string;
  timestamp: Date;
  action?: ToastAction;
}

/** A toast with an action stays a little longer, so there is time to use it */
const ACTION_TOAST_MS = 8000;

const toasts = ref<Toast[]>([]);
const history = ref<Toast[]>([]);
let nextId = 1;

function removeToast(id: number) {
  toasts.value = toasts.value.filter((toast) => toast.id !== id);
}

/** Shows a toast and returns its id. The history keeps it without the action, which only works while it shows. */
function showToast(type: ToastType, title: string, message = '', action?: ToastAction): number {
  const toast: Toast = { id: nextId++, type, title, message, timestamp: new Date(), action };
  toasts.value = [...toasts.value.slice(-3), toast];
  history.value = [{ ...toast, action: undefined }, ...history.value].slice(0, 50);
  // Errors stay long enough to be read and copied
  window.setTimeout(() => removeToast(toast.id), type === 'error' ? 15000 : action ? ACTION_TOAST_MS : 5000);
  return toast.id;
}

/** Closes the toast and runs its action, once. */
function runToastAction(id: number) {
  const action = toasts.value.find((toast) => toast.id === id)?.action;
  removeToast(id);
  action?.run();
}

/** Whether the toast is still on screen. */
const isShowing = (id: number): boolean => toasts.value.some((toast) => toast.id === id);

function clearHistory() {
  history.value = [];
}

export function useToast() {
  return { toasts: readonly(toasts), history: readonly(history), showToast, removeToast, runToastAction, isShowing, clearHistory };
}
