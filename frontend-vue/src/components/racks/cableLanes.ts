import type { RackCable, RackPort } from '@/types';
import { sideOf, type PortSide } from './rackModel';

/** Width of the cable channel right of the rail while it has room for every lane, in px */
export const CHANNEL_PX = 72;
/** Distance between two cable lanes in the channel, in px; a lane is the vertical run of one cable */
export const LANE_PX = 7;
/** Room after the last lane, in px, so the outermost cable keeps clear of the rack edge */
const AFTER_LAST_LANE_PX = 16;

/**
 * Cables that need a lane on the side shown: both jacks on that side. A cable with one end elsewhere leaves
 * as a stub instead. May count a cable whose device still waits in the tray, which only widens the channel.
 */
export function laneCount(cables: Pick<RackCable, 'a_port_id' | 'b_port_id'>[], portById: Map<number, RackPort>, side: PortSide): number {
  return cables.filter((cable) => {
    const a = portById.get(cable.a_port_id);
    const b = portById.get(cable.b_port_id);
    return !!a && !!b && sideOf(a) === side && sideOf(b) === side;
  }).length;
}

/** Channel width for that many lanes: the usual width, wider once the lanes no longer fit, so no two share one. */
export function channelWidth(lanes: number): number {
  return Math.max(CHANNEL_PX, lanes * LANE_PX + AFTER_LAST_LANE_PX);
}

/** x of a lane, counted from 0, given the channel's left edge. */
export function laneX(channelLeft: number, lane: number): number {
  return channelLeft + LANE_PX * (lane + 1);
}
