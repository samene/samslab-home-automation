"""Tests for FfmpegMp4Recorder's error paths and command construction.

Mirrors test_camera_publisher.py's subprocess-fake conventions exactly.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.plugins.camera.exceptions import CameraUnavailableError
from app.plugins.camera.recorder import FfmpegMp4Recorder


def test_start_raises_when_ffmpeg_is_not_on_path() -> None:
    recorder = FfmpegMp4Recorder(ffmpeg_path="samslab-nonexistent-ffmpeg-binary")

    with pytest.raises(CameraUnavailableError, match="not found on PATH"):
        recorder.start(
            output_path=Path("/tmp/recording.mp4"),
            width=1920,
            height=1080,
            fps=30,
            bitrate_kbps=8000,
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
    recorder = FfmpegMp4Recorder()
    defaults: dict[str, object] = {
        "output_path": Path("/tmp/samslab-agent-test/recording.mp4"),
        "width": 1920,
        "height": 1080,
        "fps": 30,
        "bitrate_kbps": 8000,
        "preset": "veryfast",
    }
    defaults.update(start_kwargs)
    recorder.start(**defaults)  # type: ignore[arg-type]
    return captured_command


def test_start_outputs_a_local_finalized_mp4_not_rtsp(monkeypatch: pytest.MonkeyPatch) -> None:
    command = _start_and_capture_command(monkeypatch)

    assert "-f" in command
    assert command[command.index("-f") + 1] == "rawvideo"  # the input format, not output
    assert "rtsp" not in command
    assert "-movflags" in command
    assert command[command.index("-movflags") + 1] == "+faststart"
    assert command[-1] == "/tmp/samslab-agent-test/recording.mp4"


def test_start_sets_explicit_bitrate_control(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same reasoning as FfmpegRtspPublisher: an uncapped CRF encode can run
    away on a long recording just as it can on a long WAN stream."""
    command = _start_and_capture_command(monkeypatch, bitrate_kbps=12000, preset="faster")

    assert command[command.index("-b:v") + 1] == "12000k"
    assert command[command.index("-maxrate") + 1] == "12000k"
    assert command[command.index("-bufsize") + 1] == "24000k"
    assert command[command.index("-preset") + 1] == "faster"


def test_start_sets_a_keyframe_interval_from_fps(monkeypatch: pytest.MonkeyPatch) -> None:
    command = _start_and_capture_command(monkeypatch, fps=10)

    assert command[command.index("-g") + 1] == "20"


def test_write_before_start_raises() -> None:
    recorder = FfmpegMp4Recorder(ffmpeg_path="samslab-nonexistent-ffmpeg-binary")

    with pytest.raises(CameraUnavailableError, match="was not started"):
        recorder.write(b"\x00")


def test_stop_before_start_is_a_no_op() -> None:
    recorder = FfmpegMp4Recorder(ffmpeg_path="samslab-nonexistent-ffmpeg-binary")
    recorder.stop()  # must not raise


def test_stop_closes_stdin_and_waits_for_a_graceful_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test: stop() must close stdin and wait() for ffmpeg to exit
    on its own (finalizing the moov atom) rather than terminate()-ing it
    first, which risks truncating the MP4 mid-finalize."""
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/ffmpeg")
    process = MagicMock()
    process.stdin = MagicMock()
    monkeypatch.setattr("subprocess.Popen", lambda *_a, **_kw: process)

    recorder = FfmpegMp4Recorder()
    recorder.start(
        output_path=Path("/tmp/recording.mp4"),
        width=1280,
        height=720,
        fps=30,
        bitrate_kbps=8000,
        preset="veryfast",
    )
    recorder.stop()

    process.stdin.close.assert_called_once()
    process.wait.assert_called_once()
    process.terminate.assert_not_called()
