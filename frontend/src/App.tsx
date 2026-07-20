import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { AppShell } from "@/components/layout/AppShell";
import { ProtectedRoute } from "@/components/layout/ProtectedRoute";
import { AuthProvider } from "@/context/AuthContext";
import { ThemeProvider } from "@/context/ThemeContext";
import { DashboardPage } from "@/pages/DashboardPage";
import { HistoryPage } from "@/pages/HistoryPage";
import { LoginPage } from "@/pages/LoginPage";
import { ScheduleEditorPage } from "@/pages/ScheduleEditorPage";
import { SchedulesPage } from "@/pages/SchedulesPage";
import { SavedMediaPage } from "@/pages/SavedMediaPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { WorkflowEditorPage } from "@/pages/WorkflowEditorPage";
import { WorkflowsPage } from "@/pages/WorkflowsPage";

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
                      <HistoryPage />
                    </AppShell>
                  </ProtectedRoute>
                }
              />
              <Route
                path="/saved-media"
                element={
                  <ProtectedRoute>
                    <AppShell>
                      <SavedMediaPage />
                    </AppShell>
                  </ProtectedRoute>
                }
              />
              <Route
                path="/workflows"
                element={
                  <ProtectedRoute>
                    <AppShell>
                      <WorkflowsPage />
                    </AppShell>
                  </ProtectedRoute>
                }
              />
              <Route
                path="/workflows/new"
                element={
                  <ProtectedRoute>
                    <AppShell>
                      <WorkflowEditorPage />
                    </AppShell>
                  </ProtectedRoute>
                }
              />
              <Route
                path="/workflows/:id/edit"
                element={
                  <ProtectedRoute>
                    <AppShell>
                      <WorkflowEditorPage />
                    </AppShell>
                  </ProtectedRoute>
                }
              />
              <Route
                path="/schedules"
                element={
                  <ProtectedRoute>
                    <AppShell>
                      <SchedulesPage />
                    </AppShell>
                  </ProtectedRoute>
                }
              />
              <Route
                path="/schedules/new"
                element={
                  <ProtectedRoute>
                    <AppShell>
                      <ScheduleEditorPage />
                    </AppShell>
                  </ProtectedRoute>
                }
              />
              <Route
                path="/schedules/:id/edit"
                element={
                  <ProtectedRoute>
                    <AppShell>
                      <ScheduleEditorPage />
                    </AppShell>
                  </ProtectedRoute>
                }
              />
              <Route
                path="/settings"
                element={
                  <ProtectedRoute>
                    <AppShell>
                      <SettingsPage />
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
