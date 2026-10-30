<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { BookOpen, Box, Bug, ExternalLink, FileText, GitBranch, Package, Scale, Tag } from 'lucide-vue-next';
import { api } from '@/api/client';
import PageHeader from '@/components/ui/PageHeader.vue';
import { PROJECT_LINKS, REACT_UI_URL } from '@/lib/project';
import { t } from '@/i18n';

/** About GravityLAN: versions, licence and where the project lives. No legal notice is invented here. */
const serverVersion = ref<string>();
const agentVersion = ref<string>();

onMounted(async () => {
  try {
    const status = await api.getSetupStatus();
    serverVersion.value = status.version;
    agentVersion.value = status.agent_version;
  } catch {
    // versions stay "–"
  }
});

const links = [
  { href: PROJECT_LINKS.repo, icon: GitBranch, label: 'about.link_repo', hint: 'github.com/SleeperXr/GravityLAN' },
  { href: PROJECT_LINKS.issues, icon: Bug, label: 'about.link_issues', hint: 'about.link_issues_hint' },
  { href: PROJECT_LINKS.releases, icon: Tag, label: 'about.link_releases', hint: 'about.link_releases_hint' },
  { href: PROJECT_LINKS.changelog, icon: FileText, label: 'about.link_changelog', hint: 'CHANGELOG.md' },
  { href: PROJECT_LINKS.dockerHub, icon: Package, label: 'about.link_docker', hint: 'sleeperxr/gravitylan' },
];
</script>

<template>
  <div class="mx-auto max-w-3xl space-y-5 px-4 py-5 md:px-8 md:py-7">
    <PageHeader :title="t('about.title')" :description="t('about.subtitle')" />

    <section class="gl-card grid gap-px overflow-hidden sm:grid-cols-3" :aria-label="t('about.versions')">
      <div class="bg-surface p-4">
        <p class="gl-eyebrow">{{ t('about.server') }}</p>
        <p class="mt-1 font-mono text-xl font-semibold text-fg tabular">{{ serverVersion ? `v${serverVersion}` : '–' }}</p>
      </div>
      <div class="bg-surface p-4">
        <p class="gl-eyebrow">{{ t('about.agent') }}</p>
        <p class="mt-1 font-mono text-xl font-semibold text-fg tabular">{{ agentVersion ? `v${agentVersion}` : '–' }}</p>
        <p class="mt-0.5 text-xs text-fg-subtle">{{ t('about.agent_hint') }}</p>
      </div>
      <div class="bg-surface p-4">
        <p class="gl-eyebrow">{{ t('about.interface') }}</p>
        <p class="mt-1 text-base font-semibold text-fg">GravityUI</p>
        <p class="mt-0.5 text-xs text-fg-subtle">
          <a :href="REACT_UI_URL" class="text-info-text hover:underline">{{ t('about.classic') }}</a>
        </p>
      </div>
    </section>

    <section class="gl-card p-5" aria-labelledby="about-links">
      <h2 id="about-links" class="text-sm font-semibold text-fg">{{ t('about.project') }}</h2>
      <p class="mt-1 max-w-prose text-sm text-fg-muted">{{ t('about.project_text') }}</p>
      <ul class="mt-3 grid gap-2 sm:grid-cols-2">
        <li v-for="link in links" :key="link.href">
          <a
            :href="link.href"
            target="_blank"
            rel="noopener noreferrer"
            class="flex items-center gap-3 rounded-md border border-line bg-raised px-3 py-2.5 transition-colors hover:border-accent/50"
          >
            <component :is="link.icon" class="size-4 shrink-0 text-accent-text" aria-hidden="true" />
            <span class="min-w-0 flex-1">
              <span class="block text-sm font-medium text-fg">{{ t(link.label) }}</span>
              <span class="block truncate font-mono text-xs text-fg-subtle">{{ link.hint.startsWith('about.') ? t(link.hint) : link.hint }}</span>
            </span>
            <ExternalLink class="size-3.5 shrink-0 text-fg-subtle" aria-hidden="true" />
          </a>
        </li>
      </ul>
    </section>

    <section class="gl-card p-5" aria-labelledby="about-license">
      <h2 id="about-license" class="flex items-center gap-2 text-sm font-semibold text-fg"><Scale class="size-4 text-fg-subtle" aria-hidden="true" />{{ t('about.license') }}</h2>
      <p class="mt-1 max-w-prose text-sm text-fg-muted">{{ t('about.license_text') }}</p>
      <p class="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        <a :href="PROJECT_LINKS.license" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-1 text-info-text hover:underline"><BookOpen class="size-3.5" aria-hidden="true" />LICENSE</a>
        <a :href="PROJECT_LINKS.notices" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-1 text-info-text hover:underline"><Box class="size-3.5" aria-hidden="true" />{{ t('about.third_party') }}</a>
      </p>
    </section>
  </div>
</template>
