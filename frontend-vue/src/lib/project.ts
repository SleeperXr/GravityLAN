/** Where the project lives, for the in-development notice and the About page. */
export const REPO_URL = 'https://github.com/SleeperXr/GravityLAN';

export const PROJECT_LINKS = {
  repo: REPO_URL,
  issues: `${REPO_URL}/issues`,
  newIssue: `${REPO_URL}/issues/new`,
  releases: `${REPO_URL}/releases`,
  changelog: `${REPO_URL}/blob/main/CHANGELOG.md`,
  license: `${REPO_URL}/blob/main/LICENSE`,
  notices: `${REPO_URL}/blob/main/THIRD_PARTY_NOTICES.md`,
  dockerHub: 'https://hub.docker.com/r/sleeperxr/gravitylan',
} as const;

/** The classic React interface; `?ui=react` keeps that choice for this browser. */
export const REACT_UI_URL = '/?ui=react';
