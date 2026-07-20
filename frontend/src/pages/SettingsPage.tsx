import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/hooks/useAuth";
import { useServiceInfo } from "@/hooks/useHealth";
import { useTheme } from "@/hooks/useTheme";
import { API_BASE_URL } from "@/lib/api/client";
import { formatTimestamp } from "@/lib/format";

const APP_VERSION = import.meta.env.VITE_APP_VERSION ?? "0.1.0";

export function SettingsPage() {
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const { data: serviceInfo } = useServiceInfo();

  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6 lg:p-8">
    <div className="flex max-w-2xl flex-col gap-4">
      <h1 className="text-lg font-semibold">Settings</h1>

      <Card>
        <CardHeader>
          <CardTitle>Profile</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Field label="Username" value={user?.username ?? "—"} />
          <Field label="Email" value={user?.email ?? "—"} />
          <Field label="Roles" value={user?.roles.join(", ") || "—"} />
          <Field label="Last login" value={formatTimestamp(user?.last_login)} />
          <Separator className="my-1" />
          <Button variant="outline" className="w-fit" onClick={() => void logout()}>
            Log out
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Appearance</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between">
            <Label htmlFor="theme-toggle">Dark mode</Label>
            <Switch
              id="theme-toggle"
              checked={theme === "dark"}
              onCheckedChange={(checked) => setTheme(checked ? "dark" : "light")}
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Server</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Field label="API base URL" value={API_BASE_URL} />
          <Field label="Server status" value={serviceInfo?.status ?? "—"} />
          <Field label="Service" value={serviceInfo?.service ?? "—"} />
          <Separator className="my-1" />
          <Field label="Application version" value={APP_VERSION} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Pump</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Field label="GPIO pin" value="PUMP_GPIO_PIN (default: 17)" />
          <Field label="Active high" value="PUMP_ACTIVE_HIGH (default: true)" />
          <Field label="Pulse duration" value="PUMP_TRIGGER_PULSE_MS (default: 200 ms)" />
          <Separator className="my-1" />
          <p className="text-sm text-muted-foreground">
            This output is intended for timer relay triggering. The Raspberry Pi only
            generates a short GPIO pulse — the timer relay it drives controls the actual
            watering duration, not the Pi. These values are configured per-agent via
            environment variables (see docs/agent/PUMP.md), not editable from this page.
          </p>
        </CardContent>
      </Card>
    </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}
