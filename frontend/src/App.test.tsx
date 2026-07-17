import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { App } from "./App";

/**
 * Renders the real, fully-composed provider tree (QueryClientProvider,
 * ThemeProvider, BrowserRouter, AuthProvider) with nothing mocked out —
 * every other test in this project mocks hooks individually, which is fast
 * but can't catch a provider nested in the wrong place (e.g. a component
 * that calls useTheme() rendered outside <ThemeProvider>). This is the one
 * test that would have caught that class of bug before it reached
 * production: a blank page with "useTheme must be used within a
 * ThemeProvider" thrown during the first render.
 */
describe("App", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("mounts without throwing and renders the login page when unauthenticated", async () => {
    render(<App />);

    expect(await screen.findByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });
});
