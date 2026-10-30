/**
 * GravityUI's backend client (./core). Only the auth side effects are set here: instead of the
 * default jump to a /login page, a 401 shows the login screen in place.
 */
import { ref } from 'vue';
import { authHandlers } from './core';

export {
  api,
  request,
  ApiError,
  createScanSocket,
  createMetricsSocket,
  createSshTerminalSocket,
} from './core';
export type { TelemetryPurge, TelemetryRetention, TelemetryStatus, TelemetryTableStats } from './core';

/** Flips to true when any request comes back 401; App.vue then shows the login screen. */
export const sessionExpired = ref(false);

authHandlers.onUnauthorized = () => {
  sessionExpired.value = true;
};
authHandlers.onLoggedOut = () => {
  sessionExpired.value = true;
};
