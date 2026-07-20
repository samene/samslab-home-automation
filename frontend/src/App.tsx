import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { AppShell } from "@/components/layout/AppShell";
import { ProtectedRoute } from "@/components/layout/ProtectedRoute";
import { AuthProvider } from "@/context/AuthContext";
import { ThemeProvider } from "@/context/ThemeContext";
import { DashboardPage } from "@/pages/DashboardPage";
import { LoginPage } from "@/pages/LoginPage";

// Dashboard and Login load eagerly (the landing page for authenticated and
// unauthenticated users respectively) — every other route is code-split so
// the initial bundle a phone downloads over a slow connection only pays for
// the page it's about to render.
const HistoryPage = lazy(() => import("@/pages/HistoryPage").then((m) => ({ default: m.HistoryPage })));
const SavedMediaPage = lazy(() =>
  import("@/pages/SavedMediaPage").then((m) => ({ default: m.SavedMediaPage })),
);
const WorkflowsPage = lazy(() =>
  import("@/pages/WorkflowsPage").then((m) => ({ default: m.WorkflowsPage })),
);
const WorkflowEditorPage = lazy(() =>
  import("@/pages/WorkflowEditorPage").then((m) => ({ default: m.WorkflowEditorPage })),
);
const SchedulesPage = lazy(() =>
  import("@/pages/SchedulesPage").then((m) => ({ default: m.SchedulesPage })),
);
const ScheduleEditorPage = lazy(() =>
  import("@/pages/ScheduleEditorPage").then((m) => ({ default: m.ScheduleEditorPage })),
);
const SettingsPage = lazy(() => import("@/pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));
const NotificationsSettingsPage = lazy(() =>
  import("@/pages/NotificationsSettingsPage").then((m) => ({ default: m.NotificationsSettingsPage })),
);

function RouteFallback() {
  return (
    <div className="flex h-full items-center justify-center">
      <Loader2 className="size-6 animate-spin text-muted-foreground" />
    </div>
  );
}

function LazyPage({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<RouteFallback />}>{children}</Suspense>;
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
    },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <BrowserRouter>
          <AuthProvider>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route
                path="/"
                element={
                  <ProtectedRoute>
                    <AppShell>
                      <DashboardPage />
                    </AppShell>
                  </ProtectedRoute>
                }
              />
              <Route
                path="/history"
                element={
                  <ProtectedRoute>
                    <AppShell>
                      <LazyPage>
                        <HistoryPage />
                      </LazyPage>
                    </AppShell>
                  </ProtectedRoute>
                }
              />
              <Route
                path="/saved-media"
                element={
                  <ProtectedRoute>
                    <AppShell>
                      <LazyPage>
                        <SavedMediaPage />
                      </LazyPage>
                    </AppShell>
                  </ProtectedRoute>
                }
              />
              <Route
                path="/workflows"
                element={
                  <ProtectedRoute>
                    <AppShell>
                      <LazyPage>
                        <WorkflowsPage />
                      </LazyPage>
                    </AppShell>
                  </ProtectedRoute>
                }
              />
              <Route
                path="/workflows/new"
                element={
                  <ProtectedRoute>
                    <AppShell>
                      <LazyPage>
                        <WorkflowEditorPage />
                      </LazyPage>
                    </AppShell>
                  </ProtectedRoute>
                }
              />
              <Route
                path="/workflows/:id/edit"
                element={
                  <ProtectedRoute>
                    <AppShell>
                      <LazyPage>
                        <WorkflowEditorPage />
                      </LazyPage>
                    </AppShell>
                  </ProtectedRoute>
                }
              />
              <Route
                path="/schedules"
                element={
                  <ProtectedRoute>
                    <AppShell>
                      <LazyPage>
                        <SchedulesPage />
                      </LazyPage>
                    </AppShell>
                  </ProtectedRoute>
                }
              />
              <Route
                path="/schedules/new"
                element={
                  <ProtectedRoute>
                    <AppShell>
                      <LazyPage>
                        <ScheduleEditorPage />
                      </LazyPage>
                    </AppShell>
                  </ProtectedRoute>
                }
              />
              <Route
                path="/schedules/:id/edit"
                element={
                  <ProtectedRoute>
                    <AppShell>
                      <LazyPage>
                        <ScheduleEditorPage />
                      </LazyPage>
                    </AppShell>
                  </ProtectedRoute>
                }
              />
              <Route
                path="/settings"
                element={
                  <ProtectedRoute>
                    <AppShell>
                      <LazyPage>
                        <SettingsPage />
                      </LazyPage>
                    </AppShell>
                  </ProtectedRoute>
                }
              />
              <Route
                path="/settings/notifications"
                element={
                  <ProtectedRoute>
                    <AppShell>
                      <LazyPage>
                        <NotificationsSettingsPage />
                      </LazyPage>
                    </AppShell>
                  </ProtectedRoute>
                }
              />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </AuthProvider>
        </BrowserRouter>
        <Toaster />
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export default App;
