"""Tests for the FrameSource backends' error paths that don't require real camera hardware."""

from __future__ import annotations

import builtins

import pytest

from app.plugins.camera.exceptions import CameraUnavailableError
from app.plugins.camera.sources import OpenCvFrameSource, Picamera2FrameSource


def _fake_import_raising(monkeypatch: pytest.MonkeyPatch, blocked_name: str) -> None:
    real_import = builtins.__import__

    def _fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == blocked_name:
            raise ImportError(f"No module named {blocked_name!r}")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _fake_import)


def test_open_raises_when_opencv_is_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_import_raising(monkeypatch, "cv2")
    source = OpenCvFrameSource(device_index=0, width=1280, height=720, fps=30)

    with pytest.raises(CameraUnavailableError, match="opencv-python is not installed"):
        source.open()


def test_close_is_a_no_op_before_open() -> None:
    source = OpenCvFrameSource(device_index=0, width=1280, height=720, fps=30)
    source.close()  # must not raise


def test_read_returns_none_before_open() -> None:
    source = OpenCvFrameSource(device_index=0, width=1280, height=720, fps=30)
    assert source.read() is None


def test_picamera2_open_raises_when_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_import_raising(monkeypatch, "picamera2")
    source = Picamera2FrameSource(width=1280, height=720, fps=30)

    with pytest.raises(CameraUnavailableError, match="picamera2 is not installed"):
        source.open()


def test_picamera2_close_is_a_no_op_before_open() -> None:
    source = Picamera2FrameSource(width=1280, height=720, fps=30)
    source.close()  # must not raise


def test_picamera2_read_returns_none_before_open() -> None:
    source = Picamera2FrameSource(width=1280, height=720, fps=30)
    assert source.read() is None
