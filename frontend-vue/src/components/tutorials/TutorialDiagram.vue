<script setup lang="ts">
import { t } from '@/i18n';
import type { DiagramKind } from './tutorials';

/**
 * Small explanatory diagrams for the tutorials. Drawn with the theme's colour variables, so they
 * follow light and dark mode; every label sits inside a box wide enough for its German text.
 */
defineProps<{ kind: DiagramKind }>();
const d = (key: string) => t(`gv.tutorials.diagram.${key}`);
const routes = [
  { key: 'l2', color: 'var(--line-1)', dash: undefined },
  { key: 'l3', color: 'var(--line-4)', dash: '6 4' },
  { key: 'probe', color: 'var(--line-3)', dash: '2 4' },
];
</script>

<template>
  <figure class="overflow-x-auto rounded-md border border-line bg-sunken p-3">
    <!-- Setup: wizard, scan subnets, first scan, overview -->
    <svg v-if="kind === 'setup'" viewBox="0 0 680 120" class="min-w-[560px]" role="img" :aria-label="d('setup_label')">
      <defs>
        <marker id="tut-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="var(--gl-fg-subtle)" />
        </marker>
      </defs>
      <g v-for="(step, i) in ['setup_1', 'setup_2', 'setup_3', 'setup_4']" :key="step" :transform="`translate(${10 + i * 170}, 30)`">
        <rect width="140" height="60" rx="10" fill="var(--gl-raised)" stroke="var(--gl-line-strong)" />
        <circle cx="20" cy="30" r="11" fill="var(--gl-accent)" />
        <text x="20" y="34" text-anchor="middle" font-size="12" font-weight="700" fill="var(--gl-accent-fg)">{{ i + 1 }}</text>
        <text x="84" y="34" text-anchor="middle" font-size="12" font-weight="600" fill="var(--gl-fg)">{{ d(step) }}</text>
      </g>
      <line v-for="i in 3" :key="i" :x1="152 + (i - 1) * 170" y1="60" :x2="176 + (i - 1) * 170" y2="60" stroke="var(--gl-fg-subtle)" stroke-width="1.5" marker-end="url(#tut-arrow)" />
    </svg>

    <!-- How GravityLAN reaches a subnet: L2 direct, L3 routed, L2 probe -->
    <svg v-else-if="kind === 'routing'" viewBox="0 0 680 210" class="min-w-[560px]" role="img" :aria-label="d('routing_label')">
      <rect x="10" y="75" width="130" height="60" rx="10" fill="var(--gl-raised)" stroke="var(--gl-accent)" stroke-width="1.5" />
      <text x="75" y="109" text-anchor="middle" font-size="13" font-weight="700" fill="var(--gl-fg)">GravityLAN</text>
      <g v-for="(row, i) in routes" :key="row.key" :transform="`translate(0, ${i * 70})`">
        <path :d="`M140 ${105 - i * 70} C 200 ${105 - i * 70}, 200 35, 260 35`" fill="none" :stroke="row.color" stroke-width="2" :stroke-dasharray="row.dash" />
        <rect x="260" y="10" width="170" height="50" rx="8" fill="var(--gl-surface)" :stroke="row.color" stroke-width="1.5" />
        <text x="345" y="31" text-anchor="middle" font-size="12" font-weight="700" fill="var(--gl-fg)">{{ d(`routing_${row.key}`) }}</text>
        <text x="345" y="48" text-anchor="middle" font-size="11" fill="var(--gl-fg-muted)">{{ d(`routing_${row.key}_how`) }}</text>
        <text x="448" y="40" font-size="11" fill="var(--gl-fg-muted)">{{ d(`routing_${row.key}_mac`) }}</text>
      </g>
    </svg>

    <!-- Agent: installed over SSH, then reports on its own -->
    <svg v-else-if="kind === 'agent'" viewBox="0 0 680 150" class="min-w-[560px]" role="img" :aria-label="d('agent_label')">
      <defs>
        <marker id="tut-arrow-agent" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="var(--gl-fg-subtle)" />
        </marker>
      </defs>
      <rect x="10" y="45" width="130" height="60" rx="10" fill="var(--gl-raised)" stroke="var(--gl-line-strong)" />
      <text x="75" y="79" text-anchor="middle" font-size="12" font-weight="600" fill="var(--gl-fg)">{{ d('agent_browser') }}</text>
      <rect x="275" y="45" width="130" height="60" rx="10" fill="var(--gl-raised)" stroke="var(--gl-accent)" stroke-width="1.5" />
      <text x="340" y="79" text-anchor="middle" font-size="13" font-weight="700" fill="var(--gl-fg)">GravityLAN</text>
      <rect x="540" y="45" width="130" height="60" rx="10" fill="var(--gl-raised)" stroke="var(--line-2)" stroke-width="1.5" />
      <text x="605" y="72" text-anchor="middle" font-size="12" font-weight="600" fill="var(--gl-fg)">{{ d('agent_host') }}</text>
      <text x="605" y="89" text-anchor="middle" font-size="11" fill="var(--gl-fg-muted)">gravitylan-agent</text>
      <line x1="142" y1="75" x2="271" y2="75" stroke="var(--gl-fg-subtle)" stroke-width="1.5" marker-end="url(#tut-arrow-agent)" />
      <text x="206" y="66" text-anchor="middle" font-size="11" fill="var(--gl-fg-muted)">{{ d('agent_click') }}</text>
      <line x1="407" y1="62" x2="536" y2="62" stroke="var(--line-2)" stroke-width="1.5" marker-end="url(#tut-arrow-agent)" />
      <text x="471" y="52" text-anchor="middle" font-size="11" fill="var(--gl-fg-muted)">{{ d('agent_ssh') }}</text>
      <line x1="536" y1="90" x2="409" y2="90" stroke="var(--gl-accent)" stroke-width="1.5" stroke-dasharray="5 4" marker-end="url(#tut-arrow-agent)" />
      <text x="471" y="112" text-anchor="middle" font-size="11" fill="var(--gl-fg-muted)">{{ d('agent_report') }}</text>
    </svg>

    <!-- Measurement data tiers -->
    <svg v-else-if="kind === 'telemetry'" viewBox="0 0 680 120" class="min-w-[560px]" role="img" :aria-label="d('telemetry_label')">
      <defs>
        <marker id="tut-arrow-tel" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="var(--gl-fg-subtle)" />
        </marker>
      </defs>
      <g v-for="(tier, i) in ['raw', 'hourly', 'daily']" :key="tier" :transform="`translate(${10 + i * 230}, 25)`">
        <rect width="190" height="70" rx="10" fill="var(--gl-raised)" :stroke="`var(--line-${[1, 4, 3][i]})`" stroke-width="1.5" />
        <text x="95" y="30" text-anchor="middle" font-size="12" font-weight="700" fill="var(--gl-fg)">{{ d(`telemetry_${tier}`) }}</text>
        <text x="95" y="50" text-anchor="middle" font-size="11" fill="var(--gl-fg-muted)">{{ d(`telemetry_${tier}_keep`) }}</text>
      </g>
      <line v-for="i in 2" :key="i" :x1="202 + (i - 1) * 230" y1="60" :x2="236 + (i - 1) * 230" y2="60" stroke="var(--gl-fg-subtle)" stroke-width="1.5" marker-end="url(#tut-arrow-tel)" />
    </svg>
  </figure>
</template>
