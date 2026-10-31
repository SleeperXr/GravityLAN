/**
 * GravityUI's backend client (./core). Only the auth side effects are set here: instead of the
 * default jump to a /login page, a 401 shows the login screen in place.
 */
import { ref } from 'vue';
import { authHandlers } from './core';
import { requestStepUp } from '@/composables/useStepUp';
import { t } from '@/i18n';

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
// A sensitive action answered with X-Step-Up opens the password dialog; the request is repeated after it
authHandlers.onStepUp = requestStepUp;
authHandlers.stepUpCancelled = () => t('gv.stepup.cancelled');
