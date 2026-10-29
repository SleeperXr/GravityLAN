/**
 * The rack entry being dragged right now. Drop targets read it during dragover, where the browser does not
 * expose the transferred data, so they can show whether the place fits before the mouse is released.
 */
import { ref } from 'vue';

export const draggingKey = ref<string | null>(null);
