import { describe, expect, it, vi } from 'vitest';
import { useToast } from './useToast';

describe('useToast', () => {
  it('runs a toast action once and closes the toast', () => {
    const { toasts, history, showToast, runToastAction, isShowing } = useToast();
    const run = vi.fn();
    const id = showToast('success', 'Moved', 'Proxmox on unit 18', { label: 'Undo', run });
    expect(isShowing(id)).toBe(true);
    expect(toasts.value.find((t) => t.id === id)?.action?.label).toBe('Undo');
    // The history outlives the toast, so it does not keep the action
    expect(history.value[0].action).toBeUndefined();

    runToastAction(id);
    runToastAction(id);
    expect(run).toHaveBeenCalledTimes(1);
    expect(isShowing(id)).toBe(false);
  });
});
