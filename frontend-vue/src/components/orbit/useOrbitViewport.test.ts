import { describe, expect, it } from 'vitest';
import { ref } from 'vue';
import { useOrbitViewport, wheelZooms } from './useOrbitViewport';

const svg = () =>
  ref({ getBoundingClientRect: () => ({ left: 0, top: 0, width: 400, height: 300 }) } as unknown as SVGSVGElement);

const wheel = (init: WheelEventInit) => new WheelEvent('wheel', { cancelable: true, clientX: 200, clientY: 150, deltaY: -100, ...init });

describe('useOrbitViewport wheel', () => {
  it('zooms on any wheel where the map has the page to itself', () => {
    expect(wheelZooms({ ctrlKey: false, metaKey: false }, false)).toBe(true);
  });

  it('needs Ctrl or Cmd where the page around the map scrolls', () => {
    expect(wheelZooms({ ctrlKey: false, metaKey: false }, true)).toBe(false);
    expect(wheelZooms({ ctrlKey: true, metaKey: false }, true)).toBe(true);
    expect(wheelZooms({ ctrlKey: false, metaKey: true }, true)).toBe(true);
  });

  it('leaves a plain wheel to the page and keeps the zoom', () => {
    const view = useOrbitViewport(svg(), ref(true), ref(true));
    const event = wheel({});
    expect(view.onWheel(event)).toBe(false);
    expect(event.defaultPrevented).toBe(false);
    expect(view.zoom.value).toBe(1);
  });

  it('zooms in around the cursor with Ctrl and keeps the page still', () => {
    const view = useOrbitViewport(svg(), ref(true), ref(true));
    const event = wheel({ ctrlKey: true });
    expect(view.onWheel(event)).toBe(true);
    expect(event.defaultPrevented).toBe(true);
    expect(view.zoom.value).toBeGreaterThan(1);
  });

  it('zooms on a plain wheel on the full map', () => {
    const view = useOrbitViewport(svg(), ref(true));
    const event = wheel({});
    expect(view.onWheel(event)).toBe(true);
    expect(event.defaultPrevented).toBe(true);
  });
});
