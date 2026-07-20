# Camera Architecture

## Purpose

Describe the camera capture, live-streaming, and future media-handling boundary.

## Scope

Live streaming — starting, stopping, and reporting the status of one RTSP
stream published to an already-deployed MediaMTX instance, viewed by the
browser over WebRTC (the frontend drives playback itself, never MediaMTX's
own embedded player page) — is implemented. High-resolution
still-image capture ("snapshot"), independent of streaming and uploaded
directly to Amazon S3, is also implemented (see "Snapshot capture" below), as
is local, high-quality video recording with direct-to-S3 upload (independent
of streaming and of MediaMTX — see the server's `docs/architecture/`
Saved Media notes and "On-sensor HDR" below). AI/vision processing is
explicitly **not** part of this phase; see Future Considerations.

## Architecture

### Live streaming (implemented)

The browser never talks to the Raspberry Pi. The full path is: browser →
cloud server REST API → `camera.stream.start`/`camera.stream.stop` commands →
agent → MediaMTX (RTSP publish) → browser (WebRTC via the WHEP protocol,
POSTing an SDP offer to the `playback_url` the server returned and attaching
the server-minted `playback_token` as a Bearer header on that POST — see
"Browser playback authentication" below).

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
different scheme/port than the one the agent publishes RTSP to — e.g. a
reverse proxy in front of MediaMTX terminating TLS). `MEDIAMTX_PLAYBACK_PORT`
may be left unset entirely, omitting the port from the constructed URL — for
when a proxy/load balancer terminates the scheme's implicit default port
(443/80) and forwards to MediaMTX's real port internally, so the browser
never needs to see it. `playback_url` points at MediaMTX's WHEP endpoint (not
MediaMTX's embedded HTML player page) — see "Browser playback authentication"
below for why. Server settings `MEDIAMTX_HOST`, `MEDIAMTX_PLAYBACK_SCHEME`,
`MEDIAMTX_PLAYBACK_PORT`, `CAMERA_STREAM_NAME`, `CAMERA_COMMAND_TIMEOUT_SECONDS`,
`CAMERA_COMMAND_POLL_INTERVAL_SECONDS` mirror the agent's MediaMTX
scheme/host/port so the server can independently construct the same playback
URL for `GET /camera/status` without depending on a live command result —
this is the URL the browser actually loads; the agent's own `playback_url()`
is only ever included in a command result for logging symmetry and is never
fetched by the browser directly.

Snapshot-specific agent settings: `CAMERA_SNAPSHOT_WIDTH`/`CAMERA_SNAPSHOT_HEIGHT`
(default 1920x1080), `CAMERA_SNAPSHOT_THUMBNAIL_WIDTH` (default 320),
`AWS_REGION`/`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_S3_BUCKET`/
`AWS_S3_PREFIX` (default `snapshots`) — all optional; leaving `AWS_S3_BUCKET`/
`AWS_ACCESS_KEY_ID` unset disables snapshot uploads entirely (streaming is
unaffected). Snapshot-specific server settings:
`CAMERA_SNAPSHOT_COMMAND_TIMEOUT_SECONDS` (default 60 — longer than
`CAMERA_COMMAND_TIMEOUT_SECONDS`'s default 15, since a standalone capture may
need to open the camera, capture, encode, and upload two files before it
completes), plus the server's own, independently configured
`AWS_REGION`/`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_S3_BUCKET`/
`AWS_PRESIGNED_URL_TTL_SECONDS` (default 300) — least-privilege credentials
distinct from the agent's own (`GetObject`/presign + `DeleteObject` only,
never `PutObject`).

### Browser playback authentication

Two approaches were tried and abandoned before landing on the current one:

1. **HTTP Basic Auth via `user:pass@host` in the URL.** Chrome (and other
   browsers) stopped honoring userinfo embedded in a URL in 2022 — the
   credentials are silently stripped, and the request goes out
   unauthenticated, so MediaMTX falls back to its native Basic Auth dialog
   (the exact "why is the browser asking for a password" symptom this was
   built to avoid).
2. **HLS via hls.js, with the JWT attached as an Authorization header.**
   This actually worked, for a while — but native Safari HLS playback
   (used whenever hls.js's `Hls.isSupported()` is false, which turned out to
   be every Safari tested, desktop and iOS) has no way to attach a custom
   header to a passive `<video src>` load at all, requiring an entire
   same-origin backend proxy (now deleted) just to work around it. Even with
   that in place, MediaMTX turned out to 302-redirect every HLS read through
   a cookie-based session-affinity mechanism, needing further workarounds on
   both ends. HLS's live segment-refresh cadence also produced a
   perceptible blank flicker every few seconds. All of this motivated the
   move to WebRTC below.

The current mechanism is **WebRTC via the WHEP protocol**
(https://mediamtx.org/docs/read/webrtc), authenticated with MediaMTX's
[JWT-based auth](https://mediamtx.org/docs/features/authentication) exactly
as HLS was — but WHEP's session setup is a normal `fetch()` POST (an SDP
offer in, an SDP answer back), not a passive resource load, so the browser
can attach the `Authorization: Bearer <token>` header itself directly. No
proxy, no cookie dance, no native-vs-programmatic-client split: `RTCPeerConnection`/
`<video>.srcObject` are uniformly supported across Chrome, Firefox, Edge,
Safari desktop, and iOS Safari.

- **Server** (`app/core/mediamtx_jwt.py`): mints a short-lived RS256 JWT per
  `camera/start`/`camera/status` call, carrying the
  `mediamtx_permissions: [{"action": "read", "path": stream_name}]` claim
  MediaMTX's `authJWTClaimKey` expects, and returns it as `playback_token`
  alongside `playback_url` (MediaMTX's `/<stream>/whep` endpoint). This is a
  *separate* RSA keypair from the app's own HS256 `JWT_SECRET` — a JWKS
  endpoint can only ever publish a public key, so signing with the app's
  shared secret would mean publishing it. `GET /.well-known/mediamtx-jwks.json`
  (no auth — JWKS endpoints are conventionally public) serves the public
  half; point mediamtx.yml's `authJWTJWKS` at
  `https://<server>/api/.well-known/mediamtx-jwks.json` in the hybrid
  deployment — the `/api` prefix matters, since Caddy only reverse-proxies
  `/api/*` to this backend (`deployment/caddy/Caddyfile`), stripping the
  prefix before forwarding; the bare path 404s through the public domain
  even though the backend's own route carries no `/api`. Generate the
  keypair with `python scripts/generate_mediamtx_jwt_key.py` and set the
  printed `MEDIAMTX_JWT_PRIVATE_KEY` (base64-encoded PKCS8 PEM, to survive
  `.env`'s bash-sourcing) plus, optionally,
  `MEDIAMTX_JWT_ISSUER`/`MEDIAMTX_JWT_AUDIENCE` to match mediamtx.yml's
  `authJWTIssuer`/`authJWTAudience` if those are set there.
  `MEDIAMTX_JWT_TTL_SECONDS` (default 60) is deliberately short — a fresh
  token is minted on every status poll, never persisted. Leaving
  `MEDIAMTX_JWT_PRIVATE_KEY` unset disables MediaMTX JWT auth entirely
  (`playback_token` stays `null`, and MediaMTX falls back to whatever other
  auth method — or none — is configured for its read path).
- **Frontend** (`CameraPanel.tsx`'s `useWebRtcPlayback` hook): creates a
  receive-only `RTCPeerConnection` (this camera has no microphone), waits
  for ICE candidate gathering to finish (bounded by a timeout — non-trickle
  ICE, chosen for simplicity/robustness over PATCH-based trickle ICE),
  POSTs the resulting SDP offer to `playback_url` with
  `Authorization: Bearer <playback_token>` and `Content-Type: application/sdp`,
  and sets the SDP answer from the response as its remote description. The
  received track is attached to the `<video>` element via `srcObject`. A
  retry loop (bounded attempts, fixed delay) covers both a rejected/failed
  initial POST and a mid-stream `connectionState` transition to `"failed"`.
  Teardown sends `DELETE` to the WHEP session URL returned in the initial
  response's `Location` header. Deployment prerequisites this needs beyond
  what HLS did: MediaMTX/its reverse proxy must expose the `Location`
  response header cross-origin (`Access-Control-Expose-Headers: Location`),
  and the deployment must allow inbound UDP for ICE/RTP media (MediaMTX's
  `webrtcICEUDPMuxAddress` single-port-mux mode is the simplest config for a
  server with a public IP).

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

### Snapshot capture (implemented)

Unlike streaming, a snapshot genuinely needs persisted metadata (a gallery
has to list, paginate, and delete past captures), so this is the first
first-class domain the camera subsystem has needed: `server/app/domains/snapshots/`
follows the Device Registry's exact vertical-slice shape (`models.py`/
`repository.py`/`service.py`/`exceptions.py`/`api.py`). Unlike Devices/Commands,
a `Snapshot` row is **hard-deleted**, not soft-deleted — its whole point is a
real S3 object, so `DELETE /snapshots/{id}` removes both the row and the
underlying objects rather than preserving an audit trail for a file that no
longer exists.

The full path: browser → `POST /camera/snapshot` → `camera.snapshot` command
(dispatched and awaited through the *same* `_create_command`/
`_wait_for_terminal` primitives `start_stream`/`stop_stream` already use, just
with a longer, snapshot-specific timeout — `_wait_for_terminal` gained an
optional `timeout_seconds` parameter for this, defaulting to today's behavior
so `start_stream`/`stop_stream` are unaffected) → agent (`CameraService.capture_snapshot`)
→ Amazon S3 (agent uploads directly via `boto3`) → the command's result carries
only object keys/metadata back to `CameraApplicationService`, which persists
it via `SnapshotService` → PostgreSQL → `GET /snapshots` (Gallery).

**Independent of streaming, sharing the same `CameraService`.** If a live
stream is already running, `capture_snapshot()` reuses the active
`FrameSource` at the stream's *current* resolution, without interrupting it —
deliberately accepting a rare torn-frame race (this method's caller thread and
`_pump_frames`'s own thread can both call `read()` concurrently) rather than
touching the live streaming path at all. If idle, it opens a *fresh*
`FrameSource` at higher, snapshot-specific `CAMERA_SNAPSHOT_WIDTH`/
`CAMERA_SNAPSHOT_HEIGHT` settings (default 1920x1080 — "high-resolution," as
opposed to whatever lower resolution streaming is configured at), captures
one frame, and closes it again immediately — a snapshot never leaves the
camera open. Both paths encode a full-size JPEG plus a `CAMERA_SNAPSHOT_THUMBNAIL_WIDTH`-wide
(default 320) thumbnail via `cv2.imencode`/`cv2.resize` — already a dependency
for streaming, so no new image library was introduced — write both to a temp
file, upload both directly to S3 (`plugins/camera/snapshot_uploader.py`'s
`S3SnapshotUploader`, keys `<prefix>/YYYY/MM/DD/<device-name>/original|thumbnails/<uuid>.jpg`,
each `put_object` verified via a `head_object` round trip, `Config(retries=...)`
for transient failures), then delete the temp files whether the upload
succeeded or failed. The handler/service return **metadata only** — bucket,
object keys, a sha256 of the original bytes, dimensions, size, timestamps —
image bytes never leave `capture_snapshot()`.

**Presigned URLs are minted only on read, only server-side, only by
`SnapshotApplicationService`.** PostgreSQL stores object keys, never a URL —
`GET /snapshots`/`GET /snapshots/{id}` mint a fresh, short-lived presigned URL
(`AWS_PRESIGNED_URL_TTL_SECONDS`, default 300s) on every response via
`app/core/s3_client.py`'s `S3Client` (the read-side mirror of the agent's
upload-side adapter — separate, least-privilege credentials: the agent's
`AWS_*` settings only ever need `PutObject`, the server's only ever need
`GetObject`/presign + `DeleteObject`). `CameraApplicationService.capture_snapshot()`
never touches S3 at all — `POST /camera/snapshot`'s response
(`CameraSnapshotDTO`) is metadata-only, with no `thumbnail_url`/`image_url`;
the frontend gets working image URLs by then querying `GET /snapshots`. The
browser always loads snapshot images directly from S3 — the backend never
proxies image bytes.

Both the agent-side (`agent/app/config/settings.py`) and server-side
(`server/app/config/settings.py`) `AWS_REGION`/`AWS_ACCESS_KEY_ID`/
`AWS_SECRET_ACCESS_KEY`/`AWS_S3_BUCKET` settings are optional and independently
configured — `None` disables the adapter (`build_s3_snapshot_uploader`/
`build_s3_client` both return `None`, mirroring `build_mediamtx_jwt_signer`'s
"optional adapter" pattern), so neither side fails to start without S3
configured; only an actual snapshot capture/read/delete fails, clearly, once
requested. `boto3`/`botocore` are imported lazily (inside the `build_*`
factory functions), matching `sources.py`'s lazy `cv2`/`picamera2` imports, so
importing either module never requires `boto3` to be installed just to run
streaming or the rest of the server.

**Metrics** (agent-side, `plugins/camera/metrics.py`): `camera_snapshots_total`,
`camera_snapshot_duration_seconds` (capture+encode, excludes upload),
`camera_snapshot_upload_duration_seconds`, `camera_snapshot_failures_total`.

### On-sensor HDR for Camera Module 3 (implemented)

`capture_snapshot()`'s fresh-open (idle) path and `start_recording()`/
`stop_recording()` both toggle the IMX708's (Camera Module 3) on-sensor HDR
mode on around their own dedicated `FrameSource`, mirroring `rpicam-still`/
`rpicam-vid --hdr sensor` — never libcamera's own software `HdrMode` control
(`Off`/`SingleExposure`/`MultiExposure`/`Night`), which fuses multiple
captured frames in the ISP rather than combining two exposures during the
sensor's own readout. libcamera has no control for the sensor's own HDR mode
at all, so — exactly like `rpicam-apps` itself (`core/options.cpp`,
`set_imx708_subdev_hdr_ctrl`) — `plugins/camera/sensor_hdr.py`'s
`set_imx708_sensor_hdr()` sets it directly: it scans
`/sys/class/video4linux/v4l-subdev*` for whichever node's `driver/module`
symlink resolves to the `imx708` kernel driver, then issues a raw
`VIDIOC_S_CTRL` ioctl (`V4L2_CID_WIDE_DYNAMIC_RANGE`) against that
`/dev/v4l-subdevN` directly — a raw `ctypes`/`fcntl` call, not a new
dependency, since it's one two-field struct.

Enabled by default (`CAMERA_HDR_SENSOR_MODE`, agent settings) but always
best-effort and silent: on any camera other than a Camera Module 3 (no
matching `imx708` subdev found, or the ioctl fails for any reason —
permission, container without `/dev`/`/sys` mapped in, older kernel), it's a
silent no-op, never an error surfaced to a snapshot/recording caller. HDR is
switched on immediately before that `FrameSource`'s own `open()` and switched
back off immediately after its `close()` — for a snapshot, that's the whole
(brief) idle-capture path; for a recording, that spans `start_recording()`
through whichever thread's `finally` actually releases the hardware (an
explicit `stop_recording()`, or the `camera_record_max_duration_seconds`
safety valve). **Live streaming is never touched**: `capture_snapshot()`'s
reuse-the-live-session branch (stream already running) skips this entirely,
and nothing in the streaming `start()`/`stop()`/`_pump_frames` path
references `sensor_hdr.py` at all — the sensor's HDR register is always left
in the same read-only-implied "off" state a live stream expects, since this
module only ever changes it around a snapshot's or a recording's *own*
dedicated open.

## Design Decisions

- The browser never connects to the Raspberry Pi, in either phase — it only
  ever negotiates WebRTC playback against a URL the cloud server constructs
  and returns (never one the frontend hardcodes or the device reports
  directly), authenticated with a JWT the server mints alongside it.
- The cloud server controls camera lifecycle entirely through the existing
  Command domain (`camera.stream.start`/`camera.stream.stop`/`camera.snapshot`)
  — streaming itself still has no camera-specific persistence, only an
  application-layer orchestration over Commands and Devices. Snapshots are
  the exception: they genuinely need persisted metadata (a gallery has to
  list/paginate/delete), so `snapshots` is a first-class domain, following the
  Device Registry's exact reference pattern — see "Snapshot capture" above.
- Camera libraries and the RTSP publish process stay inside
  `agent/app/plugins/camera/`'s `FrameSource`/`StreamPublisher` seams; no
  command handler imports OpenCV/ffmpeg directly. The snapshot path reuses
  `FrameSource` for capture and `cv2` for JPEG encode/thumbnail — no new
  image library was introduced.
- Media bytes never enter PostgreSQL or the command WebSocket. Snapshot image
  bytes go straight from the agent to Amazon S3 over `boto3`; PostgreSQL only
  ever stores metadata and S3 object keys, never a URL — presigned URLs are
  minted fresh on every read, server-side only (`SnapshotApplicationService`),
  never persisted, never hardcoded.
- MediaMTX itself is out of scope: this implementation assumes it is already
  deployed and configured, and never modifies it.

## Future Considerations

Motion triggers, AI/vision processing, encryption, redaction, and
asynchronous processing workers — all deferred past this phase. The
snapshot/recording design was deliberately kept extensible toward: scheduled
captures, a snapshot/recording taken automatically before/after a watering
command, broader automation workflows, and AI image/video analysis over
captured media — none of these require a redesign, only new callers of the
existing `camera.snapshot`/`camera.record.start`/`camera.record.stop`
commands and the Saved Media domain.

## Open Questions

What retention policy (if any) should apply to old snapshots, and should
deletion ever be automatic rather than always user-initiated? Should a future
phase report a real MediaMTX viewer count (today's `viewer_count` is always
`0`, a documented placeholder)?

## References

- [Storage](STORAGE.md)
- [Commands](COMMANDS.md)
- [Data flow](../architecture/DATAFLOW.md)
- [API](../architecture/API.md)
- [Database](../architecture/DATABASE.md)
