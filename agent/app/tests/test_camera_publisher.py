"""Tests for FfmpegRtspPublisher's error paths and command construction."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.plugins.camera.exceptions import CameraUnavailableError
from app.plugins.camera.publisher import FfmpegRtspPublisher


def test_start_raises_when_ffmpeg_is_not_on_path() -> None:
    publisher = FfmpegRtspPublisher(ffmpeg_path="samslab-nonexistent-ffmpeg-binary")

    with pytest.raises(CameraUnavailableError, match="not found on PATH"):
        publisher.start(
            publish_url="rtsp://example.invalid/camera",
            width=1280,
            height=720,
            fps=30,
            bitrate_kbps=1500,
            preset="veryfast",
        )


def _start_and_capture_command(
    monkeypatch: pytest.MonkeyPatch, **start_kwargs: object
) -> list[str]:
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/ffmpeg")
    captured_command: list[str] = []

    def _fake_popen(command: list[str], **_kwargs: object) -> MagicMock:
        captured_command.extend(command)
        process = MagicMock()
        process.stdin = MagicMock()
        return process

    monkeypatch.setattr("subprocess.Popen", _fake_popen)
    publisher = FfmpegRtspPublisher()
    defaults: dict[str, object] = {
        "publish_url": "rtsp://mediamtx.local:8554/camera",
        "width": 1280,
        "height": 720,
        "fps": 30,
        "bitrate_kbps": 1500,
        "preset": "veryfast",
    }
    defaults.update(start_kwargs)
    publisher.start(**defaults)  # type: ignore[arg-type]
    return captured_command


def test_start_forces_tcp_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression test: without -rtsp_transport tcp, ffmpeg defaults to UDP for
    the actual RTP data — across a network path where UDP doesn't reliably
    reach the server (NAT, a firewall, the public internet), the RTSP
    handshake still succeeds but no video data arrives, and MediaMTX times
    out the "idle" session a few seconds in."""
    command = _start_and_capture_command(monkeypatch)

    assert "-rtsp_transport" in command
    assert command[command.index("-rtsp_transport") + 1] == "tcp"


def test_start_sets_explicit_bitrate_control(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression test: without -b:v/-maxrate, libx264 falls back to
    open-ended CRF encoding, which can burst above what a constrained WAN
    link actually sustains — causing buffering/stalls that look far worse
    than steady, moderate quality."""
    command = _start_and_capture_command(monkeypatch, bitrate_kbps=800, preset="faster")

    assert command[command.index("-b:v") + 1] == "800k"
    assert command[command.index("-maxrate") + 1] == "800k"
    assert command[command.index("-bufsize") + 1] == "1600k"
    assert command[command.index("-preset") + 1] == "faster"


def test_start_sets_a_keyframe_interval_from_fps(monkeypatch: pytest.MonkeyPatch) -> None:
    """A keyframe roughly every 2s bounds how long a viewer or a decoder that
    dropped a frame has to wait to recover a clean picture."""
    command = _start_and_capture_command(monkeypatch, fps=10)

    assert command[command.index("-g") + 1] == "20"


def test_write_before_start_raises() -> None:
    publisher = FfmpegRtspPublisher(ffmpeg_path="samslab-nonexistent-ffmpeg-binary")

    with pytest.raises(CameraUnavailableError, match="was not started"):
        publisher.write(b"\x00")


def test_stop_before_start_is_a_no_op() -> None:
    publisher = FfmpegRtspPublisher(ffmpeg_path="samslab-nonexistent-ffmpeg-binary")
    publisher.stop()  # must not raise
