# Sam's Lab — Operator Console

A small, focused frontend for the Sam's Lab cloud server: sign in, see whether the
Raspberry Pi is online, fire a handful of quick actions, and browse command history.
This is deliberately not a large enterprise dashboard — see the root
[CLAUDE.md](../CLAUDE.md) for the project's overall architecture.

## Stack

React 19, TypeScript, Vite, TanStack Query, Tailwind CSS v4, hand-written
shadcn/ui-style components (Radix primitives + `class-variance-authority` +
`tailwind-merge`), Axios, React Router, and Vitest + Testing Library for tests.

## Getting started

```bash
cd frontend
npm install
cp .env.example .env   # defaults to http://localhost:8000
npm run dev
```

The dev server runs on `http://localhost:5173`. It talks to the cloud server at
`VITE_API_BASE_URL` (`frontend/.env`). For the two to actually talk to each other,
the server's own `.env` (repo root) needs `ALLOW_ORIGINS` to include the frontend's
origin — see the root `.env.example`, which already defaults it to
`http://localhost:5173`.

### Getting a login-capable account

There is no self-service registration endpoint (user provisioning is
administrative, by design — see `CLAUDE.md`). Create one with:

```bash
python scripts/create_user.py --username admin --email admin@example.com \
  --password 'change-me' --role Admin
```

Run from the repo root, against whatever database the server is configured to
use. The script is idempotent — re-running it with the same username is a no-op.

## Live updates: polling, not a browser WebSocket

The server's `/ws` WebSocket Gateway is **device-only authenticated** — it
completes a handshake using a device JWT, and explicitly rejects human user
tokens (see `server/tests/test_websocket_gateway.py`). There is currently no
browser-facing realtime channel in the backend, and building one that pretends
to be a device (or a client that can never complete the handshake) would be
actively wrong.

So "live updates" here means TanStack Query polling every 5 seconds
(`refetchInterval`, see `src/hooks/useDevices.ts` / `useCommands.ts`) rather than
a literal `WebSocket` connection in the browser. Every query hook that needs
freshness uses this pattern consistently. If the backend ever grows a
user-facing realtime channel, swapping the polling for a subscription is a
change scoped entirely to these hooks — no component above them needs to know.

## Project structure

```
src/
  components/
    ui/         hand-written shadcn/ui-style primitives (button, card, dialog, ...)
    shared/     StatusBadge, ActionCard, ConfirmDialog, loading skeletons
    dashboard/  Timeline (compact recent-activity list)
    history/    ActivityTable, ActivityDetailDialog (full command detail)
    layout/     AppShell (nav + topbar), ProtectedRoute
  pages/        LoginPage, DashboardPage, HistoryPage, SettingsPage
  context/      AuthContext (session), ThemeContext (dark/light)
  hooks/        useDevices, useCommands, useHealth, useAuth, useTheme
  lib/api/      axios client + interceptors, typed wrappers per REST resource
  types/api.ts  TypeScript mirror of the server's application-layer DTOs
```

State management is intentionally simple: TanStack Query owns server data
(devices, commands), plain React Context owns session and theme. There is no
Redux/Zustand/etc. — the app doesn't need it.

Single-device MVP: the dashboard shows the first registered device
(`usePrimaryDevice()` in `src/hooks/useDevices.ts`). Supporting multiple devices
later is a matter of adding a device switcher on top of the same `useDevices()`
data — nothing in the query layer needs to change.

## Testing

```bash
npm run test           # vitest run
npm run test:watch     # vitest, watch mode
npm run coverage       # vitest run --coverage
```

Tests favor correctness over exhaustive coverage — auth flow, the quick-action
confirm-then-send flow, activity selection, and the pure formatting/API-wrapper
helpers are covered; the hand-written `components/ui/**` primitives themselves
are excluded from the coverage report (see `vite.config.ts`), since they're
largely Radix pass-throughs.

## Other commands

```bash
npm run build     # tsc -b && vite build
npm run lint      # oxlint
npm run preview   # preview a production build locally
```
