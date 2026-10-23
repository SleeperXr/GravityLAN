/**
 * Entry type behind Timeline.vue.
 *
 * Adapted from the Timeline block of 8starlabs-ui (https://github.com/8starlabs/ui),
 * MIT License, Copyright (c) 2025 Tham Kei Lok. See THIRD_PARTY_NOTICES.md.
 */

export type TimelineTone = 'accent' | 'danger' | 'warn' | 'info' | 'neutral';

export interface TimelineEntry<D> {
  key: string | number;
  tone: TimelineTone;
  /** Hollow dot: a recovery rather than a problem */
  hollow?: boolean;
  data: D;
}
