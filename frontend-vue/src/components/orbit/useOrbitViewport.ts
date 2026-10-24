/**
 * Pan, zoom, pinch and smooth fly-to for the orbit map's SVG viewport.
 * World coordinates are the stored device positions; the view is translate(x, y) scale(zoom).
 */
import { ref, type Ref } from 'vue';
import type { Point } from './orbitModel';
import { easeInOutCubic, fitTransform, lerpView, zoomAround, type ViewTransform } from './orbitFocus';

export function useOrbitViewport(svgRef: Ref<SVGSVGElement | null>, reducedMotion: Ref<boolean>) {
  const viewX = ref(0);
  const viewY = ref(0);
  const zoom = ref(1);
  const isPanning = ref(false);

  let panStart: Point = { x: 0, y: 0 };
  let frame = 0;
  const pointers = new Map<number, Point>();
  let pinchStartDistance = 0;
  let pinchStartView: ViewTransform | null = null;

  const current = (): ViewTransform => ({ x: viewX.value, y: viewY.value, zoom: zoom.value });
  function apply(v: ViewTransform) {
    viewX.value = v.x;
    viewY.value = v.y;
    zoom.value = v.zoom;
  }
  function cancel() {
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
  }

  /** Glide to `target` (instant with reduced motion). */
  function animateTo(target: ViewTransform, duration = 520) {
    cancel();
    if (reducedMotion.value || duration <= 0) return apply(target);
    const from = current();
    const startedAt = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - startedAt) / duration);
      apply(lerpView(from, target, easeInOutCubic(t)));
      frame = t < 1 ? requestAnimationFrame(step) : 0;
    };
    frame = requestAnimationFrame(step);
  }

  function size() {
    const rect = svgRef.value?.getBoundingClientRect();
    return rect && rect.width > 0 && rect.height > 0 ? { width: rect.width, height: rect.height } : null;
  }

  function screenToWorld(clientX: number, clientY: number): Point {
    const rect = svgRef.value?.getBoundingClientRect();
    if (!rect) return { x: 0, y: 0 };
    return { x: (clientX - rect.left - viewX.value) / zoom.value, y: (clientY - rect.top - viewY.value) / zoom.value };
  }

  /** Show all of `points` (the whole map). False when there is nothing to fit or no size yet. */
  function fit(points: Point[], animated = false): boolean {
    const s = size();
    if (!s || points.length === 0) return false;
    const target = fitTransform(points, s.width, s.height, { padding: 0.9 });
    if (!target) return false;
    if (animated) animateTo(target);
    else apply(target);
    return true;
  }

  /** Close in on a few bodies (focus, search hit). */
  function flyTo(points: Point[]) {
    const s = size();
    if (!s || points.length === 0) return;
    const target = fitTransform(points, s.width, s.height, { margin: 140, padding: 0.72, maxZoom: 1.5 });
    if (target) animateTo(target);
  }

  function zoomBy(factor: number) {
    const s = size();
    if (!s) return;
    cancel();
    apply(zoomAround(current(), { x: s.width / 2, y: s.height / 2 }, factor));
  }

  function onWheel(e: WheelEvent) {
    e.preventDefault();
    const rect = svgRef.value?.getBoundingClientRect();
    if (!rect) return;
    cancel();
    apply(zoomAround(current(), { x: e.clientX - rect.left, y: e.clientY - rect.top }, e.deltaY < 0 ? 1.12 : 0.89));
  }

  const distance = () => {
    const [a, b] = [...pointers.values()];
    return a && b ? Math.hypot(a.x - b.x, a.y - b.y) : 0;
  };
  const midpoint = (): Point => {
    const [a, b] = [...pointers.values()];
    return a && b ? { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } : { x: 0, y: 0 };
  };

  /** Pointer down on empty space: one finger pans, a second one switches to pinch-zoom. */
  function pointerDown(e: PointerEvent): 'pan' | 'pinch' {
    cancel();
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 2) {
      isPanning.value = false;
      pinchStartDistance = distance();
      pinchStartView = current();
      return 'pinch';
    }
    isPanning.value = true;
    panStart = { x: e.clientX - viewX.value, y: e.clientY - viewY.value };
    return 'pan';
  }

  /** True when the move belonged to a pan or pinch. */
  function pointerMove(e: PointerEvent): boolean {
    if (pointers.has(e.pointerId)) pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size >= 2 && pinchStartView && pinchStartDistance > 0) {
      const rect = svgRef.value?.getBoundingClientRect();
      if (!rect) return true;
      const mid = midpoint();
      apply(zoomAround(pinchStartView, { x: mid.x - rect.left, y: mid.y - rect.top }, distance() / pinchStartDistance));
      return true;
    }
    if (isPanning.value) {
      viewX.value = e.clientX - panStart.x;
      viewY.value = e.clientY - panStart.y;
      return true;
    }
    return false;
  }

  /** True when the release ended a pan. */
  function pointerUp(e: PointerEvent): boolean {
    pointers.delete(e.pointerId);
    if (pointers.size < 2) {
      pinchStartView = null;
      pinchStartDistance = 0;
    }
    if (!isPanning.value) return false;
    isPanning.value = false;
    return true;
  }

  return { viewX, viewY, zoom, isPanning, screenToWorld, fit, flyTo, zoomBy, onWheel, pointerDown, pointerMove, pointerUp, cancel };
}
