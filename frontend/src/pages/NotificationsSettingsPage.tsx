import { CheckCircle2, MessageCircle, XCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { useNotificationStatus, useSendTestNotification } from "@/hooks/useNotifications";
import { formatRelativeTime } from "@/lib/format";
import type { NotificationProviderStatusDTO } from "@/types/api";

/**
 * A page under Settings, not a Sidebar entry — reached only via the link on
 * SettingsPage. Telegram's Enable/Bot Token/Chat ID are environment-
 * configured (TELEGRAM_ENABLED/TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID, matching
 * every other third-party credential in this codebase), so this page only
 * ever displays their current status — never a form to edit them — plus a
 * working Send Test Notification action.
 */
export function NotificationsSettingsPage() {
  const { data, isLoading } = useNotificationStatus();
  const sendTest = useSendTestNotification();

  const telegram = data?.providers.find((provider) => provider.provider === "telegram");

  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6 lg:p-8">
      <div className="flex max-w-2xl flex-col gap-4">
        <div className="flex items-center gap-2">
          <Link to="/settings" className="text-sm text-muted-foreground hover:underline">
            Settings
          </Link>
          <span className="text-sm text-muted-foreground">/</span>
          <h1 className="text-lg font-semibold">Notifications</h1>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <MessageCircle className="size-4" />
              Telegram
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {isLoading || !telegram ? (
              <div className="flex flex-col gap-2">
                <Skeleton className="h-5 w-full" />
                <Skeleton className="h-5 w-full" />
                <Skeleton className="h-9 w-40" />
              </div>
            ) : (
              <TelegramStatus provider={telegram} />
            )}

            <Separator className="my-1" />

            <div className="flex items-center justify-between gap-3">
              <p className="text-xs text-muted-foreground">
                Sends a Workflow Completed/Failed-style message right now — no workflow run required.
              </p>
              <Button
                type="button"
                size="sm"
                disabled={sendTest.isPending}
                onClick={() => sendTest.mutate()}
              >
                {sendTest.isPending ? "Sending…" : "Send Test Notification"}
              </Button>
            </div>

            {sendTest.data ? (
              <div className="flex flex-col gap-1.5 rounded-lg bg-muted p-2.5 text-xs">
                {sendTest.data.map((result) => (
                  <div key={result.provider} className="flex items-center gap-1.5">
                    {result.success ? (
                      <CheckCircle2 className="size-3.5 shrink-0 text-success" />
                    ) : (
                      <XCircle className="size-3.5 shrink-0 text-destructive" />
                    )}
                    <span className="font-medium capitalize">{result.provider}:</span>
                    <span className="text-muted-foreground">
                      {result.success ? `sent in ${result.duration_ms}ms` : result.error_message}
                    </span>
                  </div>
                ))}
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function TelegramStatus({ provider }: { provider: NotificationProviderStatusDTO }) {
  return (
    <>
      <Field
        label="Enable"
        value={
          <Badge variant={provider.enabled ? "success" : "outline"} className="rounded-full text-[11px]">
            {provider.enabled ? "Enabled" : "Disabled"}
          </Badge>
        }
      />
      <Field label="Bot Token" value="TELEGRAM_BOT_TOKEN (environment variable)" />
      <Field label="Chat ID" value="TELEGRAM_CHAT_ID (environment variable)" />
      <Field
        label="Configured"
        value={
          <Badge
            variant={provider.configured ? "success" : "outline"}
            className="rounded-full text-[11px]"
          >
            {provider.configured ? "Yes" : "No"}
          </Badge>
        }
      />
      <Separator className="my-1" />
      <Field
        label="Last attempt"
        value={
          provider.last_attempt_at ? (
            <span className="flex items-center gap-1.5">
              {provider.last_success ? (
                <CheckCircle2 className="size-3.5 text-success" />
              ) : (
                <XCircle className="size-3.5 text-destructive" />
              )}
              {formatRelativeTime(provider.last_attempt_at)}
            </span>
          ) : (
            "—"
          )
        }
      />
      {provider.last_error ? (
        <p className="text-xs text-destructive">{provider.last_error}</p>
      ) : null}
    </>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}
