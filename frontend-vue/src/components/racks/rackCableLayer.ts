import type { RackCable, RackPort } from '@/types';
import type { CableDraw, StubLabel } from './RackCables.vue';
import { REST_SAG, channelEdge, channelPath, isShortCable, laneX, loopPath, stubPath, type Point, type RackFrame } from './rackGeometry';
import { cableDefaults, ownerKeyOf, type PortSide } from './rackModel';

export type StubTarget = { ownerKey: string; side: PortSide | null; rackId: number | null };

/** Where the far end of a cable that leaves this view goes */
export interface StubPlace {
  id: string;
  text: string;
  target: StubTarget;
}

export interface CableLayerInput {
  frame: RackFrame;
  cables: RackCable[];
  portOf: (portId: number) => RackPort | undefined;
  /** Where a port's jack is drawn now, null when it is not drawn on this side of this rack */
  jackPoint: (portId: number) => Point | null;
  sagOf: (cableId: number) => number;
  laneOf: (cableId: number) => number;
  selectedKey: string | null;
  /** The cable under the pointer or lit up from outside */
  focus: number | null;
  placeOf: (port: RackPort) => StubPlace;
}

interface StubGroup {
  y: number;
  count: number;
  place: StubPlace;
}

function stateOf(input: CableLayerInput, cable: RackCable, a: RackPort, b: RackPort): CableDraw['state'] {
  const { selectedKey, focus } = input;
  const mine = selectedKey !== null && (ownerKeyOf(a) === selectedKey || ownerKeyOf(b) === selectedKey);
  if (focus === cable.id || mine) return 'active';
  return selectedKey !== null || focus !== null ? 'dim' : 'normal';
}

/** Both ends drawn: a loop between nearby jacks, otherwise a run through the channel. */
function jackToJackPath(input: CableLayerInput, cableId: number, a: Point, b: Point): string {
  const f = input.frame;
  const sag = input.sagOf(cableId);
  return isShortCable(f, a, b) ? loopPath(a, b, sag) : channelPath(a, b, laneX(f, input.laneOf(cableId)), (sag - REST_SAG) * 0.8);
}

/** One end drawn: the cable joins the bundle of this owner's cables going to the same place. */
function stubPathOf(input: CableLayerInput, groups: Map<string, StubGroup>, cableId: number, own: Point, ownPort: RackPort, farPort: RackPort): string {
  const place = input.placeOf(farPort);
  const key = `${ownerKeyOf(ownPort)}|${place.id}`;
  const group = groups.get(key) ?? { y: own.y, count: 0, place };
  const end = { x: channelEdge(input.frame), y: Math.round(group.y + 6 + Math.min(group.count, 5) * 3) };
  group.count++;
  groups.set(key, group);
  return stubPath(own, end, input.sagOf(cableId));
}

function drawOf(input: CableLayerInput, groups: Map<string, StubGroup>, cable: RackCable): CableDraw | null {
  const pa = input.portOf(cable.a_port_id);
  const pb = input.portOf(cable.b_port_id);
  if (!pa || !pb) return null;
  const a = input.jackPoint(pa.id);
  const b = input.jackPoint(pb.id);
  if (!a && !b) return null;
  const look = { id: cable.id, colour: cable.color ?? cableDefaults(pa.kind).colour, state: stateOf(input, cable, pa, pb) };
  if (a && b) return { ...look, d: jackToJackPath(input, cable.id, a, b), dashed: false };
  const d = a ? stubPathOf(input, groups, cable.id, a, pa, pb) : stubPathOf(input, groups, cable.id, b!, pb, pa);
  return { ...look, d, dashed: true };
}

/** Everything the cable layer draws, and where each stub label leads. */
export function buildCableLayer(input: CableLayerInput): { draws: CableDraw[]; labels: StubLabel[]; targets: Map<string, StubTarget> } {
  const groups = new Map<string, StubGroup>();
  const draws = input.cables.map((cable) => drawOf(input, groups, cable)).filter((draw): draw is CableDraw => draw !== null);
  const x = channelEdge(input.frame);
  const labels = [...groups].map(([key, g]) => ({ key, x, y: Math.round(g.y - 5), text: g.count > 1 ? `${g.place.text} · ${g.count}` : g.place.text }));
  return { draws, labels, targets: new Map([...groups].map(([key, g]) => [key, g.place.target])) };
}
