import { createContext, useCallback, useEffect, useState, type ReactNode } from "react";
import { getCurrentUser, login as loginRequest, logout as logoutRequest } from "@/lib/api/auth";
import { clearTokens, getRefreshToken, setTokens, subscribe } from "@/lib/api/tokenStore";
import type { LoginRequest, UserDTO } from "@/types/api";

type AuthStatus = "loading" | "authenticated" | "unauthenticated";

interface AuthContextValue {
  status: AuthStatus;
  user: UserDTO | null;
  login: (credentials: LoginRequest) => Promise<void>;
  logout: () => Promise<void>;
}

// eslint-disable-next-line react-refresh/only-export-components
export const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<UserDTO | null>(null);

  const loadCurrentUser = useCallback(async () => {
    try {
      const profile = await getCurrentUser();
      setUser(profile);
      setStatus("authenticated");
    } catch {
      clearTokens();
      setUser(null);
      setStatus("unauthenticated");
    }
  }, []);

  // On first load, a persisted refresh token means the interceptor can mint
  // a fresh access token on the very first authenticated request — /auth/me
  // itself is enough to trigger that and confirm the session is still valid.
  useEffect(() => {
    if (getRefreshToken()) {
      void loadCurrentUser();
    } else {
      setStatus("unauthenticated");
    }
  }, [loadCurrentUser]);

  // If something outside this component (the response interceptor, after a
  // failed refresh) clears the tokens, reflect that immediately.
  useEffect(
    () =>
      subscribe(() => {
        if (!getRefreshToken()) {
          setUser(null);
          setStatus("unauthenticated");
        }
      }),
    [],
  );

  const login = useCallback(async (credentials: LoginRequest) => {
    const tokens = await loginRequest(credentials);
    setTokens({ accessToken: tokens.access_token, refreshToken: tokens.refresh_token });
    await loadCurrentUser();
  }, [loadCurrentUser]);

  const logout = useCallback(async () => {
    const refreshToken = getRefreshToken();
    if (refreshToken) {
      await logoutRequest(refreshToken).catch(() => {
        // Best-effort: the token is cleared locally either way.
      });
    }
    clearTokens();
    setUser(null);
    setStatus("unauthenticated");
  }, []);

  return (
    <AuthContext.Provider value={{ status, user, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
