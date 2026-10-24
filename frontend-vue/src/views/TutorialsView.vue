<script setup lang="ts">
import { ArrowRight, Check, Copy, Lightbulb } from 'lucide-vue-next';
import { ref } from 'vue';
import PageHeader from '@/components/ui/PageHeader.vue';
import TutorialDiagram from '@/components/tutorials/TutorialDiagram.vue';
import { TUTORIAL_GROUPS, TUTORIALS, stepsOf } from '@/components/tutorials/tutorials';
import { PROJECT_LINKS } from '@/lib/project';
import { t } from '@/i18n';

/** Getting started: one guide per area, with steps, an example, a hint and a diagram where it helps. */
const copied = ref<string | null>(null);

async function copy(id: string, text: string) {
  try {
    await navigator.clipboard.writeText(text);
    copied.value = id;
    window.setTimeout(() => (copied.value = copied.value === id ? null : copied.value), 1600);
  } catch {
    // clipboard blocked (plain http): the code stays selectable
  }
}

const inGroup = (group: string) => TUTORIALS.filter((tut) => tut.group === group);
const tx = (id: string, field: string) => t(`gv.tutorials.${id}.${field}`);
</script>

<template>
  <div class="mx-auto max-w-[1200px] px-4 py-5 md:px-8 md:py-7">
    <PageHeader :title="t('gv.tutorials.title')" :description="t('gv.tutorials.subtitle')" />

    <!-- Phone and tablet: a scroll strip of topics -->
    <nav class="-mx-4 mt-5 mb-4 flex gap-2 overflow-x-auto px-4 pb-1 xl:hidden" :aria-label="t('gv.tutorials.index')">
      <a
        v-for="tut in TUTORIALS"
        :key="tut.id"
        :href="`#tut-${tut.id}`"
        class="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1.5 text-xs font-medium text-fg-muted hover:text-fg"
      >
        <component :is="tut.icon" class="size-3.5" aria-hidden="true" />{{ tx(tut.id, 'title') }}
      </a>
    </nav>

    <div class="grid grid-cols-[minmax(0,1fr)] gap-6 xl:mt-6 xl:grid-cols-[220px_minmax(0,1fr)]">
      <!-- Desktop: index next to the guides -->
      <nav class="sticky top-4 hidden self-start xl:block" :aria-label="t('gv.tutorials.index')">
        <div v-for="group in TUTORIAL_GROUPS" :key="group" class="mb-4">
          <p class="gl-eyebrow mb-1.5">{{ t(`gv.tutorials.group_${group}`) }}</p>
          <a
            v-for="tut in inGroup(group)"
            :key="tut.id"
            :href="`#tut-${tut.id}`"
            class="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-fg-muted hover:bg-control-hover hover:text-fg"
          >
            <component :is="tut.icon" class="size-4 shrink-0" aria-hidden="true" />{{ tx(tut.id, 'title') }}
          </a>
        </div>
        <a :href="PROJECT_LINKS.issues" target="_blank" rel="noopener noreferrer" class="mt-2 block px-2 text-xs text-info-text hover:underline">{{ t('gv.tutorials.missing') }}</a>
      </nav>

      <div class="min-w-0 space-y-8">
        <section v-for="group in TUTORIAL_GROUPS" :key="group" :aria-labelledby="`tut-group-${group}`">
          <h2 :id="`tut-group-${group}`" class="gl-eyebrow mb-3">{{ t(`gv.tutorials.group_${group}`) }}</h2>
          <div class="space-y-4">
            <article v-for="tut in inGroup(group)" :id="`tut-${tut.id}`" :key="tut.id" class="gl-card scroll-mt-4 space-y-4 p-5">
              <header class="flex items-start gap-3">
                <span class="grid size-9 shrink-0 place-items-center rounded-md bg-accent/10 text-accent-text"><component :is="tut.icon" class="size-4.5" aria-hidden="true" /></span>
                <div class="min-w-0 flex-1">
                  <h3 class="text-base font-semibold text-fg">{{ tx(tut.id, 'title') }}</h3>
                  <p class="mt-0.5 text-sm text-fg-muted">{{ tx(tut.id, 'summary') }}</p>
                </div>
                <RouterLink
                  v-if="tut.to"
                  :to="tut.to"
                  class="hidden shrink-0 items-center gap-1 rounded-md border border-line bg-control px-2.5 py-1.5 text-xs font-medium text-fg hover:border-line-strong sm:inline-flex"
                >
                  {{ t('gv.tutorials.open') }}<ArrowRight class="size-3.5" aria-hidden="true" />
                </RouterLink>
              </header>

              <TutorialDiagram v-if="tut.diagram" :kind="tut.diagram" />

              <ol class="space-y-2">
                <li v-for="(step, i) in stepsOf(tx(tut.id, 'steps'))" :key="i" class="flex gap-3 text-sm text-fg">
                  <span class="grid size-5 shrink-0 place-items-center rounded-full bg-raised font-mono text-[11px] font-semibold text-fg-muted">{{ i + 1 }}</span>
                  <span class="min-w-0 pt-px">{{ step }}</span>
                </li>
              </ol>

              <div v-if="tut.code" class="relative">
                <pre class="overflow-x-auto rounded-md border border-line bg-sunken p-3 pr-10 font-mono text-xs leading-relaxed text-fg"><code>{{ tut.code }}</code></pre>
                <button
                  type="button"
                  class="absolute top-2 right-2 grid size-7 place-items-center rounded text-fg-subtle hover:bg-control-hover hover:text-fg"
                  :aria-label="t('gv.tutorials.copy')"
                  :title="t('gv.tutorials.copy')"
                  @click="copy(tut.id, tut.code)"
                >
                  <Check v-if="copied === tut.id" class="size-3.5 text-accent-text" aria-hidden="true" /><Copy v-else class="size-3.5" aria-hidden="true" />
                </button>
              </div>

              <p class="flex gap-2.5 rounded-md border border-info/25 bg-info/[0.06] p-3 text-sm text-fg-muted">
                <Lightbulb class="mt-0.5 size-4 shrink-0 text-info-text" aria-hidden="true" />
                <span>{{ tx(tut.id, 'hint') }}</span>
              </p>

              <RouterLink v-if="tut.to" :to="tut.to" class="inline-flex items-center gap-1 text-xs font-medium text-info-text hover:underline sm:hidden">
                {{ t('gv.tutorials.open') }}<ArrowRight class="size-3.5" aria-hidden="true" />
              </RouterLink>
            </article>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>
