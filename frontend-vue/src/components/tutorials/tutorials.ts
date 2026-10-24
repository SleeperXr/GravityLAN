import type { Component } from 'vue';
import {
  Activity,
  Archive,
  Database,
  Grid3x3,
  HardDrive,
  KeyRound,
  LayoutDashboard,
  Network,
  PackageCheck,
  Router,
  Server,
  SquareTerminal,
  Webhook,
} from 'lucide-vue-next';

export type DiagramKind = 'setup' | 'routing' | 'agent' | 'telemetry';

/**
 * One guide on the Tutorials page. Its texts live under `gv.tutorials.<id>` (title, summary,
 * steps as lines, hint); `code` is shown as a copyable example, `to` links to the page it explains.
 */
export interface Tutorial {
  id: string;
  group: 'start' | 'network' | 'hosts' | 'operate';
  icon: Component;
  to?: string;
  diagram?: DiagramKind;
  code?: string;
}

export const TUTORIAL_GROUPS = ['start', 'network', 'hosts', 'operate'] as const;

export const TUTORIALS: Tutorial[] = [
  { id: 'setup', group: 'start', icon: Grid3x3, to: '/settings#subnets', diagram: 'setup' },
  { id: 'dashboard', group: 'start', icon: LayoutDashboard, to: '/' },
  { id: 'ip', group: 'network', icon: Network, to: '/network', diagram: 'routing' },
  { id: 'router', group: 'network', icon: Router, to: '/settings#subnets' },
  { id: 'topology', group: 'network', icon: Server, to: '/topology' },
  { id: 'agent', group: 'hosts', icon: HardDrive, to: '/agents', diagram: 'agent' },
  { id: 'updates', group: 'hosts', icon: PackageCheck, to: '/agents' },
  { id: 'ssh', group: 'hosts', icon: SquareTerminal, to: '/ssh' },
  { id: 'health', group: 'operate', icon: Activity, to: '/health' },
  { id: 'telemetry', group: 'operate', icon: Database, to: '/settings#telemetry', diagram: 'telemetry' },
  {
    id: 'api',
    group: 'operate',
    icon: Webhook,
    to: '/settings#tokens',
    code: 'curl -H "Authorization: Bearer <API-Token>" http://gravitylan.local:8000/api/devices',
  },
  { id: 'backup', group: 'operate', icon: Archive, to: '/settings#backup' },
  {
    id: 'unraid',
    group: 'operate',
    icon: KeyRound,
    code: [
      'docker run -d --name gravitylan \\',
      '  -p 8000:8000 \\',
      '  -v /mnt/user/appdata/gravitylan:/app/data \\',
      '  -e PUID=99 -e PGID=100 \\',
      '  --cap-add=NET_RAW --cap-add=NET_ADMIN \\',
      '  sleeperxr/gravitylan:latest',
    ].join('\n'),
  },
];

/** Steps are stored as one translated string, one step per line. */
export const stepsOf = (text: string) => text.split('\n').map((s) => s.trim()).filter(Boolean);
