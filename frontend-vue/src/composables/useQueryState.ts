import { computed, shallowRef, type WritableComputedRef } from 'vue';
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router';

/** How a value travels through the query string. `parse` returns undefined for a value it does not accept. */
export interface QueryCodec<T> {
  parse(raw: string): T | undefined;
  format(value: T): string;
}

export const queryCodecs = {
  string: { parse: (raw: string) => raw, format: (value: string) => value } satisfies QueryCodec<string>,
  oneOf<T extends string>(values: readonly T[]): QueryCodec<T> {
    return { parse: (raw) => (values.includes(raw as T) ? (raw as T) : undefined), format: (value) => value };
  },
  nullableInt: {
    parse: (raw: string) => (/^-?\d+$/.test(raw) ? Number(raw) : undefined),
    format: (value: number | null) => (value === null ? '' : String(value)),
  } satisfies QueryCodec<number | null>,
};

/**
 * Writes made in one tick, merged into a single router.replace: resetting three filters at once
 * must not leave the URL with only the last one, because each write would otherwise start from
 * the query before the previous navigation landed. Reads see these values right away.
 */
const pending = shallowRef<LocationQueryRaw | null>(null);

/**
 * A page filter that lives in the URL (?key=value), so Back, a reload and a shared link show the
 * same view. The default value is left out of the URL; a value the codec does not accept reads as
 * the default. Writes replace the history entry instead of adding one per keystroke.
 */
export function useQueryState<T>(key: string, fallback: T, codec: QueryCodec<T>): WritableComputedRef<T> {
  const route = useRoute();
  const router = useRouter();

  return computed<T>({
    get() {
      const source = pending.value && key in pending.value ? pending.value : route.query;
      const raw = source[key];
      const value = Array.isArray(raw) ? raw[0] : raw;
      if (typeof value !== 'string') return fallback;
      const parsed = codec.parse(value);
      return parsed === undefined ? fallback : parsed;
    },
    set(value) {
      const next: LocationQueryRaw = { ...(pending.value ?? route.query) };
      const formatted = value === fallback ? '' : codec.format(value);
      // A removed key stays in `pending` as undefined, so reads see it gone before the navigation lands
      next[key] = formatted === '' ? undefined : formatted;
      const scheduled = pending.value !== null;
      pending.value = next;
      if (scheduled) return;
      queueMicrotask(() => {
        const query = Object.fromEntries(Object.entries(pending.value ?? {}).filter(([, v]) => v !== undefined));
        void router.replace({ query }).finally(() => {
          pending.value = null;
        });
      });
    },
  });
}
