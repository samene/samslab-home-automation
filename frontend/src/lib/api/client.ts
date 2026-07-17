import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";
import type { TokenPairDTO } from "@/types/api";
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from "./tokenStore";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export const apiClient = axios.create({ baseURL: API_BASE_URL });

/** A second, header-free client used only for the refresh call, to avoid interceptor recursion. */
const refreshClient = axios.create({ baseURL: API_BASE_URL });

apiClient.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers.set("Authorization", `Bearer ${token}`);
  }
  return config;
});

// Only one refresh should ever be in flight, even if several requests 401 at once.
let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return null;

  refreshPromise ??= refreshClient
    .post<TokenPairDTO>("/auth/refresh", { refresh_token: refreshToken })
    .then((response) => {
      setTokens({
        accessToken: response.data.access_token,
        refreshToken: response.data.refresh_token,
      });
      return response.data.access_token;
    })
    .catch(() => {
      clearTokens();
      return null;
    })
    .finally(() => {
      refreshPromise = null;
    });

  return refreshPromise;
}

interface RetryableConfig extends InternalAxiosRequestConfig {
  _retried?: boolean;
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetryableConfig | undefined;
    const status = error.response?.status;
    const isAuthEndpoint = config?.url?.startsWith("/auth/");

    if (status === 401 && config && !config._retried && !isAuthEndpoint) {
      config._retried = true;
      const newToken = await refreshAccessToken();
      if (newToken) {
        config.headers.set("Authorization", `Bearer ${newToken}`);
        return apiClient(config);
      }
    }
    return Promise.reject(error);
  },
);
