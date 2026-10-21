import { onBeforeUnmount, ref } from 'vue';

/** Two-step buttons for destructive actions: the first click arms one for 5 s, the second runs it. */
export function useArmed<T extends string>() {
  const armed = ref<T | null>(null);
  let timer: number | undefined;

  function arm(kind: T) {
    window.clearTimeout(timer);
    armed.value = kind;
    timer = window.setTimeout(() => (armed.value = null), 5000);
  }

  function disarm() {
    window.clearTimeout(timer);
    armed.value = null;
  }

  /** True when `kind` was armed (the caller runs the action); otherwise arms it and returns false. */
  function confirmOrArm(kind: T): boolean {
    if (armed.value === kind) {
      disarm();
      return true;
    }
    arm(kind);
    return false;
  }

  onBeforeUnmount(() => window.clearTimeout(timer));
  return { armed, arm, disarm, confirmOrArm };
}
