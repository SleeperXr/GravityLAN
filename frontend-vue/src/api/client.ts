/**
 * GravityUI talks to the backend through the same client as the React UI (frontend/src/api).
 * Only the auth side effects differ: instead of jumping to the React /login page, a 401 shows
 * the Vue login screen in place.
 */
import { ref } from 'vue';
import { authHandlers } from '@shared/api/client';

export {
  api,
  request,
  ApiError,
  createScanSocket,
  createMetricsSocket,
  createSshTerminalSocket,
} from '@shared/api/client';
export type { TelemetryPurge, TelemetryRetention, TelemetryStatus, TelemetryTableStats } from '@shared/api/client';

/** Flips to true when any request comes back 401; App.vue then shows the login screen. */
export const sessionExpired = ref(false);

authHandlers.onUnauthorized = () => {
  sessionExpired.value = true;
};
authHandlers.onLoggedOut = () => {
  sessionExpired.value = true;
};
