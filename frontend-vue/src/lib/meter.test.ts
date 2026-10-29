import { describe, expect, it } from 'vitest';
import { fillScale, fillShift, stackedLayers } from './meter';

describe('meter fills', () => {
  it('shifts a rounded fill left by the part that is not filled', () => {
    expect(fillShift(30)).toBe('translateX(-70%)');
    expect(fillShift(100)).toBe('translateX(0%)');
  });

  it('keeps fills inside the track for values out of range', () => {
    expect(fillShift(140)).toBe('translateX(0%)');
    expect(fillShift(-5)).toBe('translateX(-100%)');
    expect(fillScale(Number.NaN)).toBe('scaleX(0)');
  });

  it('scales a square fill from its left edge', () => {
    expect(fillScale(25)).toBe('scaleX(0.25)');
  });

  it('stacks segments so each layer ends where its segment ends, the first drawn last', () => {
    const layers = stackedLayers(
      [
        { key: 'a', value: 50 },
        { key: 'b', value: 25 },
        { key: 'c', value: 0 },
      ],
      100,
    );
    expect(layers.map((l) => [l.key, l.transform])).toEqual([
      ['c', 'scaleX(0.75)'],
      ['b', 'scaleX(0.75)'],
      ['a', 'scaleX(0.5)'],
    ]);
  });

  it('draws nothing for an empty total', () => {
    expect(stackedLayers([{ value: 3 }], 0)[0].transform).toBe('scaleX(0)');
  });
});
