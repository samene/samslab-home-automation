"""Best-effort on-sensor HDR toggle for the Raspberry Pi Camera Module 3 (IMX708).

Mirrors ``rpicam-apps --hdr sensor`` exactly (see
``raspberrypi/rpicam-apps``'s ``core/options.cpp``,
``set_imx708_subdev_hdr_ctrl``) rather than libcamera's own software
``HdrMode`` control (``Off``/``SingleExposure``/``MultiExposure``/``Night``):
the IMX708's on-sensor HDR (combining two exposures during the sensor's own
readout, not a software-fused multi-frame capture) is a vendor-specific V4L2
control libcamera itself never exposes. rpicam-apps sets it directly via a
raw ``VIDIOC_S_CTRL`` ioctl on the sensor's own ``/dev/v4l-subdevN`` node,
found by scanning sysfs for the ``imx708`` kernel driver — so this module
does the same thing rather than going through picamera2's ``set_controls()``,
which has no equivalent for this mode at all.

Deliberately raw ``ctypes``/``fcntl``, not a v4l2 Python binding — there's no
existing dependency on one anywhere in this codebase, and the whole ioctl is
one struct with two ``u32``/``s32`` fields (``struct v4l2_control``), not
worth adding a package for. Every failure here (no Camera Module 3 present,
permission denied, running in a container without ``/dev/v4l-subdev*``
mapped in, an unexpected kernel/driver layout) is swallowed and logged as a
warning — this is a quality enhancement, never something that should block a
snapshot or recording from working at all, on this or any other camera.
"""

from __future__ import annotations

import contextlib
import ctypes
import fcntl
import glob
import os

import structlog

logger = structlog.get_logger(__name__)

# struct v4l2_control { __u32 id; __s32 value; }; — see <linux/videodev2.h>.
_VIDIOC_S_CTRL = 0xC008561C
# V4L2_CID_CAMERA_CLASS_BASE (0x009A0900) + 21, per <linux/v4l2-controls.h>.
_V4L2_CID_WIDE_DYNAMIC_RANGE = 0x009A0915


class _V4L2Control(ctypes.Structure):
    _fields_ = [("id", ctypes.c_uint32), ("value", ctypes.c_int32)]


def _find_imx708_subdev_nodes() -> list[str]:
    """Sysfs scan for every ``/dev/v4l-subdevN`` driven by the ``imx708`` kernel driver.

    Matches rpicam-apps' own traversal: for each ``v4l-subdevN`` exposed
    under ``/sys/class/video4linux``, follow its ``device/driver/module``
    symlink and check whether the resolved path names the ``imx708`` driver.
    No camera-id disambiguation (unlike rpicam-apps, which supports multiple
    simultaneous cameras) — this codebase has no multi-camera support
    anywhere else either, so every matching subdev is used as-is.
    """
    nodes: list[str] = []
    for entry in sorted(glob.glob("/sys/class/video4linux/v4l-subdev*")):
        driver_module_link = os.path.join(entry, "device", "driver", "module")
        try:
            resolved = os.path.realpath(driver_module_link)
        except OSError:
            continue
        if "imx708" in resolved:
            nodes.append(f"/dev/{os.path.basename(entry)}")
    return nodes


def set_imx708_sensor_hdr(enabled: bool) -> bool:
    """Best-effort: toggle the IMX708's on-sensor HDR mode; never raises.

    Returns whether at least one matching subdevice actually accepted the
    control. ``False`` is the expected, silent outcome on any camera other
    than a Camera Module 3 — that's not a failure worth surfacing to a
    snapshot/recording caller, only worth a debug-level trail via the
    per-node warning logged on an actual I/O error.
    """
    applied = False
    for dev_node in _find_imx708_subdev_nodes():
        fd = -1
        try:
            fd = os.open(dev_node, os.O_RDONLY)
            ctrl = _V4L2Control(id=_V4L2_CID_WIDE_DYNAMIC_RANGE, value=1 if enabled else 0)
            fcntl.ioctl(fd, _VIDIOC_S_CTRL, ctrl)
            applied = True
        except OSError as error:
            logger.warning(
                "imx708_sensor_hdr_toggle_failed",
                dev_node=dev_node,
                enabled=enabled,
                error=str(error),
            )
        finally:
            if fd != -1:
                with contextlib.suppress(OSError):
                    os.close(fd)
    return applied
