/**
 * Holds the current session's tokens outside of React state, so the axios
 * interceptors (which run outside any component) always see the latest
 * values. The access token lives in memory only; the refresh token is
 * persisted to localStorage so a page reload doesn't force a fresh login.
 *
 * `subscribe` lets AuthContext re-render when a request interceptor forces a
 * logout (e.g. the refresh token itself is rejected) without the two modules
 * importing each other.
 */

const REFRESH_TOKEN_KEY = "samslab.refresh_token";

let accessToken: string | null = null;
let refreshToken: string | null = localStorage.getItem(REFRESH_TOKEN_KEY);

type Listener = () => void;
const listeners = new Set<Listener>();

function notify() {
  for (const listener of listeners) listener();
}

export function getAccessToken() {
  return accessToken;
}

export function getRefreshToken() {
  return refreshToken;
}

export function setTokens(next: { accessToken: string; refreshToken: string }) {
  accessToken = next.accessToken;
  refreshToken = next.refreshToken;
  localStorage.setItem(REFRESH_TOKEN_KEY, next.refreshToken);
  notify();
}

export function clearTokens() {
  accessToken = null;
  refreshToken = null;
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  notify();
}

export function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
