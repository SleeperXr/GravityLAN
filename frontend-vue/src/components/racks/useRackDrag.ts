/**
 * Dragging with the pointer: a faceplate in the rack, an entry from the store, or a new piece of equipment from
 * the palette. A mouse lifts after a few px; a finger has to rest for a moment first, so a swipe still scrolls
 * the page. Where the pointer is decides what a drop means: a unit of the rack, the store, or "no rack". Escape
 * puts everything back.
 */
import { onBeforeUnmount, ref } from 'vue';
import type { FaceKind } from './rackKinds';
import type { RackEntry } from './rackModel';

/** Elements that accept a drop carry `data-rack-drop` with one of these */
export type DropZone = 'stage' | 'store' | 'unrack';

export interface DragSubject {
  /** Entry key, or `new:<kind>` for equipment that does not exist yet */
  key: string;
  label: string;
  face: FaceKind;
  height: number;
  /** Rack item kind of new equipment */
  itemKind: string | null;
  /** The entry, when it exists: in this rack, or a device without a rack */
  entry: RackEntry | null;
  from: 'rack' | 'store' | 'palette';
}

export interface DragTarget {
  unit: number;
  /** Why it does not fit there, or null when it does */
  blocker: string | null;
}

export interface DragState extends DragSubject {
  lifted: boolean;
  /** Pointer, in client coordinates */
  x: number;
  y: number;
  /** Where the faceplate was grabbed, from its top left corner, so it does not jump to the pointer */
  grabX: number;
  grabY: number;
  zone: DropZone | null;
  target: DragTarget | null;
}

export interface DragHandlers {
  /** The unit under the pointer and whether the subject fits there; null outside the rack */
  locate: (drag: DragState) => DragTarget | null;
  drop: (drag: DragState) => void;
  /** Released without moving: a click */
  click: (subject: DragSubject) => void;
}

const LIFT_PX = 4;
const TOUCH_HOLD_MS = 280;
const TOUCH_SLOP_PX = 8;

export function useRackDrag(handlers: DragHandlers) {
  const drag = ref<DragState | null>(null);
  let pointerId = -1;
  let startX = 0;
  let startY = 0;
  let holdTimer = 0;

  function start(subject: DragSubject, event: PointerEvent, grab: { x: number; y: number }) {
    if (event.button !== 0) return;
    end();
    pointerId = event.pointerId;
    startX = event.clientX;
    startY = event.clientY;
    drag.value = { ...subject, lifted: false, x: event.clientX, y: event.clientY, grabX: grab.x, grabY: grab.y, zone: null, target: null };
    if (event.pointerType === 'touch') holdTimer = window.setTimeout(lift, TOUCH_HOLD_MS);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', end);
    window.addEventListener('keydown', onKey);
    window.addEventListener('touchmove', blockScroll, { passive: false });
  }

  function lift() {
    const d = drag.value;
    if (!d) return;
    d.lifted = true;
    navigator.vibrate?.(8);
    update(d.x, d.y);
  }

  function update(x: number, y: number) {
    const d = drag.value;
    if (!d) return;
    d.x = x;
    d.y = y;
    const zone = document.elementFromPoint(x, y)?.closest<HTMLElement>('[data-rack-drop]')?.dataset.rackDrop;
    d.zone = zone === 'stage' || zone === 'store' || zone === 'unrack' ? zone : null;
    d.target = d.zone === 'stage' ? handlers.locate(d) : null;
  }

  function onMove(event: PointerEvent) {
    const d = drag.value;
    if (!d || event.pointerId !== pointerId) return;
    if (!d.lifted) {
      const dist = Math.hypot(event.clientX - startX, event.clientY - startY);
      if (event.pointerType === 'touch') {
        // Moving before the hold is up is a swipe: the page scrolls and nothing is dragged
        if (dist > TOUCH_SLOP_PX) end();
        return;
      }
      if (dist < LIFT_PX) return;
      d.lifted = true;
    }
    update(event.clientX, event.clientY);
  }

  function onUp(event: PointerEvent) {
    if (event.pointerId !== pointerId) return;
    const d = drag.value;
    end();
    if (!d) return;
    if (d.lifted) handlers.drop(d);
    else handlers.click(d);
  }

  function onKey(event: KeyboardEvent) {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    end();
  }

  function blockScroll(event: TouchEvent) {
    if (drag.value?.lifted) event.preventDefault();
  }

  function end() {
    window.clearTimeout(holdTimer);
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
    window.removeEventListener('pointercancel', end);
    window.removeEventListener('keydown', onKey);
    window.removeEventListener('touchmove', blockScroll);
    pointerId = -1;
    drag.value = null;
  }

  onBeforeUnmount(end);
  return { drag, start, cancel: end };
}
