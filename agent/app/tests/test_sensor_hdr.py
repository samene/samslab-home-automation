"""Tests for set_imx708_sensor_hdr: sysfs discovery, the raw V4L2 ioctl, and
best-effort failure handling — no real hardware, /dev, or /sys access ever
happens; every OS-level call is monkeypatched.

Patches target string dotted paths (``"app.plugins.camera.sensor_hdr.glob.glob"``)
rather than the imported ``glob``/``os``/``fcntl`` module objects directly —
mypy's strict/no-implicit-reexport mode otherwise flags accessing those as
attributes of ``sensor_hdr`` itself as an unexported attribute.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.plugins.camera import sensor_hdr


def test_returns_false_when_no_subdev_matches_imx708(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.plugins.camera.sensor_hdr.glob.glob", lambda _pattern: [])

    assert sensor_hdr.set_imx708_sensor_hdr(True) is False


def test_ignores_a_subdev_driven_by_a_different_sensor(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []

    def _fake_open(path: str, _flags: int) -> int:
        opened.append(path)
        return 3

    monkeypatch.setattr(
        "app.plugins.camera.sensor_hdr.glob.glob",
        lambda _pattern: ["/sys/class/video4linux/v4l-subdev0"],
    )
    monkeypatch.setattr(
        "app.plugins.camera.sensor_hdr.os.path.realpath", lambda _path: "/sys/module/imx219"
    )
    monkeypatch.setattr("app.plugins.camera.sensor_hdr.os.open", _fake_open)

    assert sensor_hdr.set_imx708_sensor_hdr(True) is False
    assert opened == []


def test_opens_and_ioctls_every_matching_imx708_subdev(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    closed: list[int] = []
    ioctl_calls: list[tuple[int, int, Any]] = []

    def _fake_open(path: str, _flags: int) -> int:
        opened.append(path)
        return 7

    def _fake_ioctl(fd: int, request: int, ctrl: Any) -> None:
        ioctl_calls.append((fd, request, ctrl))

    monkeypatch.setattr(
        "app.plugins.camera.sensor_hdr.glob.glob",
        lambda _pattern: [
            "/sys/class/video4linux/v4l-subdev0",
            "/sys/class/video4linux/v4l-subdev1",
        ],
    )
    monkeypatch.setattr(
        "app.plugins.camera.sensor_hdr.os.path.realpath", lambda _path: "/sys/module/imx708"
    )
    monkeypatch.setattr("app.plugins.camera.sensor_hdr.os.open", _fake_open)
    monkeypatch.setattr("app.plugins.camera.sensor_hdr.os.close", lambda fd: closed.append(fd))
    monkeypatch.setattr("app.plugins.camera.sensor_hdr.fcntl.ioctl", _fake_ioctl)

    result = sensor_hdr.set_imx708_sensor_hdr(True)

    assert result is True
    assert opened == ["/dev/v4l-subdev0", "/dev/v4l-subdev1"]
    assert closed == [7, 7]
    assert len(ioctl_calls) == 2
    for fd, request, ctrl in ioctl_calls:
        assert fd == 7
        assert request == sensor_hdr._VIDIOC_S_CTRL
        assert ctrl.id == sensor_hdr._V4L2_CID_WIDE_DYNAMIC_RANGE
        assert ctrl.value == 1


def test_passes_zero_when_disabling(monkeypatch: pytest.MonkeyPatch) -> None:
    ioctl_calls: list[Any] = []

    monkeypatch.setattr(
        "app.plugins.camera.sensor_hdr.glob.glob",
        lambda _pattern: ["/sys/class/video4linux/v4l-subdev0"],
    )
    monkeypatch.setattr(
        "app.plugins.camera.sensor_hdr.os.path.realpath", lambda _path: "/sys/module/imx708"
    )
    monkeypatch.setattr("app.plugins.camera.sensor_hdr.os.open", lambda _path, _flags: 5)
    monkeypatch.setattr("app.plugins.camera.sensor_hdr.os.close", lambda _fd: None)
    monkeypatch.setattr(
        "app.plugins.camera.sensor_hdr.fcntl.ioctl",
        lambda _fd, _req, ctrl: ioctl_calls.append(ctrl),
    )

    sensor_hdr.set_imx708_sensor_hdr(False)

    assert ioctl_calls[0].value == 0


def test_a_missing_driver_module_symlink_is_not_a_match(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(_path: str) -> str:
        raise OSError("no such file")

    monkeypatch.setattr(
        "app.plugins.camera.sensor_hdr.glob.glob",
        lambda _pattern: ["/sys/class/video4linux/v4l-subdev0"],
    )
    monkeypatch.setattr("app.plugins.camera.sensor_hdr.os.path.realpath", _raise)

    assert sensor_hdr.set_imx708_sensor_hdr(True) is False


def test_ioctl_failure_on_one_subdev_is_swallowed_and_others_still_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A permission error or unsupported control on one node must not stop
    the loop from still applying to the rest, and must never raise."""
    call_count = 0

    def _ioctl(_fd: int, _req: int, _ctrl: Any) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OSError("Invalid argument")

    monkeypatch.setattr(
        "app.plugins.camera.sensor_hdr.glob.glob",
        lambda _pattern: [
            "/sys/class/video4linux/v4l-subdev0",
            "/sys/class/video4linux/v4l-subdev1",
        ],
    )
    monkeypatch.setattr(
        "app.plugins.camera.sensor_hdr.os.path.realpath", lambda _path: "/sys/module/imx708"
    )
    monkeypatch.setattr("app.plugins.camera.sensor_hdr.os.open", lambda _path, _flags: 4)
    monkeypatch.setattr("app.plugins.camera.sensor_hdr.os.close", lambda _fd: None)
    monkeypatch.setattr("app.plugins.camera.sensor_hdr.fcntl.ioctl", _ioctl)

    result = sensor_hdr.set_imx708_sensor_hdr(True)

    assert result is True  # the second subdev still succeeded
    assert call_count == 2


def test_open_failure_is_swallowed_and_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_open(_path: str, _flags: int) -> int:
        raise PermissionError("Permission denied")

    monkeypatch.setattr(
        "app.plugins.camera.sensor_hdr.glob.glob",
        lambda _pattern: ["/sys/class/video4linux/v4l-subdev0"],
    )
    monkeypatch.setattr(
        "app.plugins.camera.sensor_hdr.os.path.realpath", lambda _path: "/sys/module/imx708"
    )
    monkeypatch.setattr("app.plugins.camera.sensor_hdr.os.open", _raise_open)

    assert sensor_hdr.set_imx708_sensor_hdr(True) is False
