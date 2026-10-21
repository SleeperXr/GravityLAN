import { defineStore } from 'pinia';
import { ref } from 'vue';

/** Number of live SSH terminals, for the nav badge (same role as Ssh/sessionCount.ts in React). */
export const useSshSessions = defineStore('sshSessions', () => {
  const liveCount = ref(0);
  function setLiveCount(count: number) {
    liveCount.value = count;
  }
  return { liveCount, setLiveCount };
});
