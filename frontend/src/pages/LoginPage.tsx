import { Cpu, LogIn } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { LogoMark } from "@/components/layout/Logo";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/hooks/useAuth";
import { getErrorMessage } from "@/lib/api/errors";

export function LoginPage() {
  const { status, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (status === "authenticated") {
    const redirectTo = (location.state as { from?: string } | null)?.from ?? "/";
    return <Navigate to={redirectTo} replace />;
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await login({ username, password });
      navigate("/", { replace: true });
    } catch (err) {
      setError(getErrorMessage(err, "Invalid username or password"));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="login-gradient-backdrop relative flex min-h-svh items-center justify-center overflow-hidden p-4">
      <CircuitBackground />

      <Card className="animate-scale-in relative w-full max-w-sm rounded-3xl border-none bg-card/90 shadow-2xl backdrop-blur-md">
        <CardHeader className="items-center text-center">
          <LogoMark className="mb-2 size-14 rounded-2xl" />
          <CardTitle className="text-xl">Sam's Lab</CardTitle>
          <CardDescription className="text-sm">Home Automation Mission Control</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                autoComplete="username"
                autoFocus
                className="h-11 rounded-xl"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                className="h-11 rounded-xl"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </div>

            <label className="flex items-center gap-2 py-1 text-sm text-muted-foreground">
              <input
                type="checkbox"
                checked={rememberMe}
                onChange={(event) => setRememberMe(event.target.checked)}
                className="size-4 rounded border-input accent-primary coarse:size-5"
              />
              Remember me
            </label>

            {error ? <p className="text-sm text-destructive">{error}</p> : null}

            <Button
              type="submit"
              size="lg"
              className="h-11 rounded-xl text-sm font-semibold"
              disabled={isSubmitting}
            >
              {isSubmitting ? (
                "Signing in…"
              ) : (
                <>
                  <LogIn className="size-4" />
                  Sign in
                </>
              )}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

/** A faint circuit-board motif behind the login card — decorative only. */
function CircuitBackground() {
  return (
    <div className="pointer-events-none absolute inset-0 opacity-[0.07]" aria-hidden="true">
      <Cpu className="absolute top-[8%] left-[10%] size-24 -rotate-12" strokeWidth={0.75} />
      <Cpu className="absolute right-[8%] bottom-[10%] size-32 rotate-6" strokeWidth={0.75} />
      <Cpu className="absolute top-[45%] right-[20%] size-16 rotate-3" strokeWidth={0.75} />
    </div>
  );
}
