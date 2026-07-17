import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "@/lib/api/auth";
import { useAuth } from "@/hooks/useAuth";
import { clearTokens } from "@/lib/api/tokenStore";
import { AuthProvider } from "./AuthContext";

vi.mock("@/lib/api/auth");

function TestConsumer() {
  const { status, user, login, logout } = useAuth();
  return (
    <div>
      <p>status: {status}</p>
      <p>user: {user?.username ?? "none"}</p>
      <button onClick={() => void login({ username: "sam", password: "secret" })}>
        Log in
      </button>
      <button onClick={() => void logout()}>Log out</button>
    </div>
  );
}

const USER = {
  id: "user-1",
  username: "sam",
  email: "sam@example.com",
  enabled: true,
  roles: ["Admin"],
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  last_login: null,
};

describe("AuthProvider", () => {
  beforeEach(() => {
    // tokenStore keeps its access/refresh tokens in module-level variables, not just
    // localStorage, so they'd otherwise leak between tests within this file.
    clearTokens();
    vi.resetAllMocks();
  });

  it("starts unauthenticated when there is no persisted refresh token", async () => {
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByText("status: unauthenticated")).toBeInTheDocument());
  });

  it("logs in and exposes the current user", async () => {
    vi.mocked(authApi.login).mockResolvedValue({
      access_token: "access-token",
      refresh_token: "refresh-token",
      token_type: "bearer",
      expires_in: 900,
    });
    vi.mocked(authApi.getCurrentUser).mockResolvedValue(USER);

    const user = userEvent.setup();
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByText("status: unauthenticated")).toBeInTheDocument());

    await user.click(screen.getByText("Log in"));

    await waitFor(() => expect(screen.getByText("status: authenticated")).toBeInTheDocument());
    expect(screen.getByText("user: sam")).toBeInTheDocument();
  });

  it("logs out and clears the current user", async () => {
    vi.mocked(authApi.login).mockResolvedValue({
      access_token: "access-token",
      refresh_token: "refresh-token",
      token_type: "bearer",
      expires_in: 900,
    });
    vi.mocked(authApi.getCurrentUser).mockResolvedValue(USER);
    vi.mocked(authApi.logout).mockResolvedValue(undefined);

    const user = userEvent.setup();
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByText("status: unauthenticated")).toBeInTheDocument());
    await user.click(screen.getByText("Log in"));
    await waitFor(() => expect(screen.getByText("status: authenticated")).toBeInTheDocument());

    await user.click(screen.getByText("Log out"));
    await waitFor(() => expect(screen.getByText("status: unauthenticated")).toBeInTheDocument());
    expect(screen.getByText("user: none")).toBeInTheDocument();
  });
});
