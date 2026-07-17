# Camera Architecture

## Purpose

Describe the camera capture, live-streaming, and future media-handling boundary.

## Scope

Live streaming — starting, stopping, and reporting the status of one RTSP
stream published to an already-deployed MediaMTX instance, viewed by the
browser through MediaMTX's own playback page — is implemented. Still-image
capture, video recording, object-storage upload, and AI/vision processing are
explicitly **not** part of this phase; see Future Considerations.

## Architecture

### Live streaming (implemented)

The browser never talks to the Raspberry Pi. The full path is: browser →
cloud server REST API → `camera.stream.start`/`camera.stream.stop` commands →
agent → MediaMTX (RTSP publish) → browser (hls.js fetches the HLS manifest
the server returned, attaching the server-minted `playback_token` as a Bearer
header on every request — see "Browser playback authentication" below).

**Server side** (`server/app/application/services/camera_service.py`,
`server/app/api/camera.py`) has no Camera domain and no camera-specific
persistence — `CameraApplicationService` is a pure orchestration layer over
the existing Command and Device application services. `POST /camera/start`
creates a `camera.stream.start` command against the (single-device MVP's)
primary device, then polls the command until it reaches a terminal state
(`CAMERA_COMMAND_TIMEOUT_SECONDS`/`CAMERA_COMMAND_POLL_INTERVAL_SECONDS`),
raising a `CameraCommandFailedError`/`CameraCommandTimedOutError` if it
doesn't complete successfully — never returning before the device has
confirmed the stream is actually live. `GET /camera/status` never dispatches
a fresh command (that would add a round trip to a simple status read);
instead it derives running/idle state from the most recent completed
`camera.stream.start`/`camera.stream.stop` commands for the device.
`playback_url` is always built server-side from `MEDIAMTX_HOST`/
`MEDIAMTX_PLAYBACK_PORT`/`CAMERA_STREAM_NAME` — the server never forwards a
URL string reported by the device for something the browser is about to load.
`playback_token`, alongside it, is a short-lived JWT minted server-side (see
"Browser playback authentication" below).

**Agent side** (`agent/app/plugins/camera/`) registers three handlers —
`camera.stream.start`, `camera.stream.stop`, `camera.status` — on the same
`CommandRegistry` the built-in `system.*` handlers use, following the
project's stated philosophy that a new command type is "a new handler,
never a runtime change" (see [Commands](COMMANDS.md)). `CameraService`
(`plugins/camera/service.py`) owns the single active stream's lifecycle
behind two small seams: `FrameSource` (frame capture) and `StreamPublisher`
(`FfmpegRtspPublisher` — OpenCV has no built-in RTSP *publish* sink, so a
system `ffmpeg` binary does the H.264 encode and RTSP push; frames are piped
to it as raw BGR24 over stdin). Publishing always forces `-rtsp_transport
tcp` — ffmpeg otherwise defaults to UDP for the actual RTP data while only
the RTSP control channel is TCP, so the initial handshake and MediaMTX's
"is publishing" log line both succeed either way, but across any network
path where UDP isn't reliably reaching the server (NAT, a firewall, or the
public internet) no video data actually arrives; MediaMTX then times out the
session as idle a few seconds in. RTP-over-TCP-interleaved avoids needing a
second, separate data path at all. The actual read-and-publish loop runs on a
background thread, never the agent's asyncio event loop — command handlers
call into `CameraService` through `loop.run_in_executor` so a slow camera or
a stalled publisher never blocks the heartbeat or WebSocket receive loop.
Only one stream is supported at a time: starting while already streaming, or
stopping while already stopped, both return success rather than an error,
matching how an operator expects a toggle-like control to behave.

`FrameSource` has two implementations, and `CameraService` picks between them
automatically (`importlib.util.find_spec("picamera2")`, preferring it when
present): `Picamera2FrameSource` wraps `libcamera` via `picamera2` — the
**only** way to reach a CSI camera module (Camera Module 3, etc.) on current
Raspberry Pi hardware, since the Pi 5's SoC has no V4L2 compatibility shim
the way older Pi 3/4 boards briefly did; `OpenCvFrameSource` wraps
`cv2.VideoCapture` and only ever works for a plain USB/UVC webcam, which V4L2
does handle natively. Getting `picamera2` working requires installing it
via `apt`, not `pip` — see Configuration below.

**Command results** (`camera.stream.start` → `stream_name`, `playback_url`,
`resolution`, `fps`, `started_at`; `camera.stream.stop` → `duration`,
`frames_sent`, `stopped_at`; `camera.status` → `running`, `uptime`,
`stream_name`, `playback_url`) are plain dicts returned from each handler's
`execute()`, exactly like the built-in `system.*` handlers — no new result
schema was introduced.

**Health** folds into the existing plugin health-check mechanism
(`check_plugins()` in `agent/app/health/checks.py` already aggregates every
plugin's `check_health()`): `CameraPlugin.check_health()` reports
`camera_detected` (a `/dev/videoN` existence probe, or `True` while actively
streaming), `mediamtx_reachable` (a bounded TCP connect to the RTSP port),
`rtsp_connected`/`streaming` (both equal to "currently streaming," since this
implementation only holds an RTSP connection while a stream is active) in its
`detail` string, but only flips `healthy=False` once a stream attempt has
actually failed — a camera that's simply never been used, or MediaMTX being
briefly unreachable while idle, are not failures.

**Metrics** (`agent/app/plugins/camera/metrics.py`): `camera_stream_active`
(gauge), `camera_stream_duration_seconds` (histogram, observed on stop),
`camera_stream_start_total`/`camera_stream_stop_total` (counters, incremented
once per successful start/stop), `camera_frames_sent_total` (counter,
incremented per published frame), `camera_stream_errors_total` (counter,
incremented on any open/publish failure) — same module-level
`prometheus_client` pattern as `agent/app/metrics/registry.py`.

**Logging**: every handler logs `command_id`, `stream_name`, `playback_url`,
`resolution`, `fps`, and (on stop) `duration`/`frames_sent`. The RTSP publish
URL is **never** logged with credentials —
`CameraService.redacted_publish_url()` strips `MEDIAMTX_USERNAME`/
`MEDIAMTX_PASSWORD` before anything touches a log line; only
`_rtsp_publish_url()` (private, used solely to hand the real URL to the
publisher) carries them.

**Configuration**: agent settings `MEDIAMTX_HOST`, `MEDIAMTX_PORT` (RTSP
publish port), `MEDIAMTX_USERNAME`, `MEDIAMTX_PASSWORD`, `STREAM_NAME`,
`CAMERA_DEVICE_INDEX`, `CAMERA_WIDTH`, `CAMERA_HEIGHT`, `CAMERA_FPS`,
`CAMERA_BITRATE_KBPS` (default 1500 — a starting point for 720p over a modest
WAN link, not a universal default; tune it to what the actual path between
agent and MediaMTX sustains, see "Tuning quality over a long/constrained
link" below), `CAMERA_PRESET` (libx264 speed/efficiency trade-off, default
`veryfast` — a Pi 5 has enough headroom over the original `ultrafast` for
meaningfully better quality at the same bitrate), plus
`MEDIAMTX_PLAYBACK_SCHEME`/`MEDIAMTX_PLAYBACK_PORT` (not in the original field
list, but required so the agent's own `camera.stream.start` result can
include a `playback_url`, since MediaMTX serves browser playback on a
different scheme/port than the one the agent publishes RTSP to — e.g. HLS
rather than WebRTC when only TCP reaches the server, or a reverse proxy in
front of MediaMTX terminating TLS). `MEDIAMTX_PLAYBACK_PORT` may be left
unset entirely, omitting the port from the constructed URL — for when a
proxy/load balancer terminates the scheme's implicit default port (443/80)
and forwards to MediaMTX's real port internally, so the browser never needs
to see it. `playback_url` points at the raw `index.m3u8` manifest (not
MediaMTX's embedded HTML player page) — see "Browser playback authentication"
below for why. Server settings `MEDIAMTX_HOST`, `MEDIAMTX_PLAYBACK_SCHEME`,
`MEDIAMTX_PLAYBACK_PORT`, `CAMERA_STREAM_NAME`, `CAMERA_COMMAND_TIMEOUT_SECONDS`,
`CAMERA_COMMAND_POLL_INTERVAL_SECONDS` mirror the agent's MediaMTX
scheme/host/port so the server can independently construct the same playback
URL for `GET /camera/status` without depending on a live command result —
this is the URL the browser actually loads; the agent's own `playback_url()`
is only ever included in a command result for logging symmetry and is never
fetched by the browser directly.

### Browser playback authentication

Two approaches were tried and abandoned before landing on MediaMTX's
JWT-based read auth:

1. **HTTP Basic Auth via `user:pass@host` in the URL.** Chrome (and other
   browsers) stopped honoring userinfo embedded in a URL in 2022 — the
   credentials are silently stripped, and the request goes out
   unauthenticated, so MediaMTX falls back to its native Basic Auth dialog
   (the exact "why is the browser asking for a password" symptom this was
   built to avoid).
2. **A plain `<iframe>`/`<video src>` load with credentials passed some other
   way.** MediaMTX's HLS and WebRTC reads accept neither query-parameter
   credentials (`?user=`/`?pass=`/`?token=`, which the RTSP/RTMP protocols
   *do* support) nor a custom `Authorization` header from a passive resource
   load — there is no URL shape that carries auth for these two protocols.

The only mechanism that actually works for a browser is MediaMTX's
[JWT-based auth](https://mediamtx.org/docs/features/authentication) plus its
documented "Embed in a website" pattern
(https://mediamtx.org/docs/read/web-browsers#embed-in-a-website): drive
playback with a real HLS client (hls.js) that can attach an `Authorization:
Bearer <token>` header to every manifest/segment request. Accordingly:

- **Server** (`app/core/mediamtx_jwt.py`): mints a short-lived RS256 JWT per
  `camera/start`/`camera/status` call, carrying the
  `mediamtx_permissions: [{"action": "read", "path": stream_name}]` claim
  MediaMTX's `authJWTClaimKey` expects, and returns it as `playback_token`
  alongside `playback_url`. This is a *separate* RSA keypair from the app's
  own HS256 `JWT_SECRET` — a JWKS endpoint can only ever publish a public
  key, so signing with the app's shared secret would mean publishing it.
  `GET /.well-known/mediamtx-jwks.json` (no auth — JWKS endpoints are
  conventionally public) serves the public half; point mediamtx.yml's
  `authJWTJWKS` at `https://<server>/api/.well-known/mediamtx-jwks.json` in
  the hybrid deployment — the `/api` prefix matters, since Caddy only
  reverse-proxies `/api/*` to this backend (`deployment/caddy/Caddyfile`),
  stripping the prefix before forwarding; the bare path 404s through the
  public domain even though the backend's own route carries no `/api`.
  Generate the keypair with
  `python scripts/generate_mediamtx_jwt_key.py` and set the printed
  `MEDIAMTX_JWT_PRIVATE_KEY` (base64-encoded PKCS8 PEM, to survive `.env`'s
  bash-sourcing) plus, optionally, `MEDIAMTX_JWT_ISSUER`/`MEDIAMTX_JWT_AUDIENCE`
  to match mediamtx.yml's `authJWTIssuer`/`authJWTAudience` if those are set
  there. `MEDIAMTX_JWT_TTL_SECONDS` (default 60) is deliberately short — a
  fresh token is minted on every status poll, never persisted. Leaving
  `MEDIAMTX_JWT_PRIVATE_KEY` unset disables MediaMTX JWT auth entirely
  (`playback_token` stays `null`, and MediaMTX falls back to whatever other
  auth method — or none — is configured for its read path).
- **Frontend** (`LiveCameraCard.tsx`): renders a `<video>` element driven by
  `hls.js`, whose `xhrSetup` callback attaches `playback_token` as a Bearer
  header on every request. Native Safari HLS (used when `Hls.isSupported()`
  is false) has no way to carry a custom header at all — a known,
  unavoidable gap for that one browser path.

### Agent publish authentication

MediaMTX only runs one `authMethod` at a time — there's no way to run
`internal` (username/password) for the agent's RTSP publish alongside `jwt`
for browser reads. Once a deployment sets `authMethod: jwt` in mediamtx.yml,
the agent's publish connection needs a JWT too, not just
`MEDIAMTX_USERNAME`/`MEDIAMTX_PASSWORD`:

- **Server**: `CameraApplicationService.start_stream` mints a *publish* JWT
  (`mediamtx_permissions: [{"action": "publish", "path": stream_name}]`, via
  `MediaMTXJWTSigner.mint_publish_token`) whenever MediaMTX JWT auth is
  configured, and includes it as `mediamtx_publish_token` in the
  `camera.stream.start` command's payload — the only channel the agent has
  back to the server (it only speaks the WebSocket protocol, never REST).
  Its TTL is `MEDIAMTX_JWT_PUBLISH_TTL_SECONDS` (default 86400 — a full day,
  deliberately much longer than the read token's, since a stream can run for
  hours and the agent has no token-refresh logic). Omitted (empty payload)
  when `MEDIAMTX_JWT_PRIVATE_KEY` isn't configured.
- **Agent** (`CameraStreamStartHandler.execute`, `CameraService.start`):
  reads `mediamtx_publish_token` from the command's arguments and, when
  present, appends it as a `?token=` query parameter — MediaMTX's actual
  documented mechanism for a protocol like RTSP that has no request header to
  attach a Bearer token to (see
  https://mediamtx.org/docs/features/authentication) —
  `rtsp://host:port/stream?token=<jwt>`. This is *not* RTSP Basic Auth's
  username/password fields: an earlier version of this code embedded the JWT
  as the password with an arbitrary username (`rtsp://token:<jwt>@host/stream`),
  which produces a confusing `token is malformed: token contains an invalid
  number of segments` error from MediaMTX — it ends up base64-decoding the
  Basic-Auth blob and trying to parse *that* as a JWT, not the password alone.
  Falls back to real RTSP Basic Auth via the static
  `MEDIAMTX_USERNAME`/`MEDIAMTX_PASSWORD` settings when no token is present
  — for a MediaMTX instance not using JWT auth at all (e.g. local
  development with `authMethod: internal`).

`ffmpeg` is a system binary, not pip-installable — install it via the OS
package manager (`apt install ffmpeg`), and is always invoked with
`-rtsp_transport tcp`: without it, ffmpeg defaults to UDP for the actual RTP
data while only the RTSP control channel is TCP, so the initial "publishing"
handshake succeeds either way, but across a network path where UDP isn't
reliably reaching the server (NAT, a firewall, the public internet) no video
data arrives and MediaMTX times out the session as idle a few seconds in.

### Tuning quality over a long/constrained link

The ffmpeg command sets explicit rate control (`-b:v`/`-maxrate` pinned to
`CAMERA_BITRATE_KBPS`, `-bufsize` at 2x that) rather than leaving libx264 on
its CRF default. This is deliberate: CRF targets a quality level with an
open-ended, bursty bitrate, which is fine on a local network but on a long,
bandwidth-constrained WAN path (e.g. a Pi in India publishing to a server in
Europe) an unbounded burst above what the path actually sustains causes
buffering/stalls that look far worse than steady, moderate quality. A
keyframe is also forced roughly every 2 seconds (`-g`, derived from
`CAMERA_FPS`) so a viewer joining mid-stream, or a decoder that drops a
frame on a lossy path, only ever waits that long to recover a clean picture.

Levers, roughly in order of impact for a constrained cross-continental link:

1. **`CAMERA_BITRATE_KBPS`** — the single biggest lever. Pick a value your
   actual sustained throughput comfortably covers, not just headline
   bandwidth (which a long-RTT path rarely delivers in full); 1500 is a
   reasonable starting point for 720p, 800-1000 for a more constrained link.
   Test with something like `iperf3` between the Pi and the server first if
   you don't already know the sustained figure.
2. **`CAMERA_WIDTH`/`CAMERA_HEIGHT`/`CAMERA_FPS`** — fewer pixels and fewer
   frames both directly reduce how many bits are needed for a given
   perceived quality at a fixed bitrate. Dropping from 1280x720 to 960x540,
   or from 30fps to 15-20fps, often improves *perceived* quality more than
   raising the bitrate would, since the encoder has fewer pixels/frames to
   spend the same budget on.
3. **`CAMERA_PRESET`** — `veryfast` is the default; a slower preset (`faster`,
   `fast`) trades more CPU/latency for better compression efficiency (more
   visual quality per bit) if the Pi's CPU has headroom to spare.

Camera backend installation is genuinely different depending on the
hardware, and this is worth being explicit about rather than papering over:

- **USB/UVC webcam** — `pip install './agent[camera]'` (the `camera` extra
  in `agent/pyproject.toml`, currently `opencv-python-headless`) is enough;
  `OpenCvFrameSource`'s guarded import keeps the rest of the agent (including
  its test suite) working fine without a camera or this extra installed.
- **CSI camera module (Camera Module 3, etc.)** — `pip install picamera2`
  alone will not produce a working install: the real `libcamera` Python
  bindings only ship via the OS's own build
  (`sudo apt install python3-picamera2`), so the agent's venv must be created
  with `--system-site-packages` to see them at all. A venv created the
  normal, isolated way will report `picamera2 is not installed` even after
  the apt package is present, because it's simply not on that venv's
  `sys.path`.

### Still images and recording (future)

A camera driver would expose typed capture capabilities; the agent would
validate a `TAKE_PHOTO` command, invoke the driver, write a temporary local
artifact, calculate metadata/checksum, move it atomically into the spool,
obtain server-authorized upload details, upload over TLS, and emit an
event/result with an object reference. Failures would remain durable for
retry under retention and disk limits. None of this is implemented yet.

## Design Decisions

- The browser never connects to the Raspberry Pi, in either phase — it only
  ever fetches the HLS manifest at a URL the cloud server constructs and
  returns (never one the frontend hardcodes or the device reports directly),
  authenticated with a JWT the server mints alongside it.
- The cloud server controls camera lifecycle entirely through the existing
  Command domain (`camera.stream.start`/`camera.stream.stop`) — there is no
  camera-specific persistence or domain, only an application-layer
  orchestration over Commands and Devices.
- Camera libraries and the RTSP publish process stay inside
  `agent/app/plugins/camera/`'s `FrameSource`/`StreamPublisher` seams; no
  command handler imports OpenCV/ffmpeg directly.
- Camera libraries remain inside drivers for the future capture path, too.
  Media bytes will never enter PostgreSQL or the command WebSocket; the
  server will record metadata and authorization, S3-compatible storage will
  hold binary objects.
- MediaMTX itself is out of scope: this implementation assumes it is already
  deployed and configured, and never modifies it.

## Future Considerations

Still-image capture (`TAKE_PHOTO`), video segments/recording, thumbnails,
motion triggers, S3 upload, AI/vision processing, encryption, redaction, and
asynchronous processing workers — all deferred past this phase.

## Open Questions

What resolution, capture cadence, local retention, and privacy zones will the
future capture path require? Should a future phase report a real MediaMTX
viewer count (today's `viewer_count` is always `0`, a documented placeholder)?

## References

- [Storage](STORAGE.md)
- [Commands](COMMANDS.md)
- [Data flow](../architecture/DATAFLOW.md)
- [API](../architecture/API.md)
