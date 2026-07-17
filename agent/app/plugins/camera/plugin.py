"""The camera plugin: lifecycle hooks and health reporting over a ``CameraService``."""

from __future__ import annotations

import asyncio

from app.plugins.base import Plugin, PluginHealthCheck
from app.plugins.camera.service import CameraService


class CameraPlugin(Plugin):
    """Advertises the ``camera`` capability and folds stream health into plugin health."""

    name = "camera"
    capabilities = ("camera",)

    def __init__(self, camera_service: CameraService) -> None:
        self._camera_service = camera_service

    async def on_shutdown(self) -> None:
        """Stop any in-progress stream so ffmpeg/the camera device aren't left open."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._camera_service.stop)

    def check_health(self) -> PluginHealthCheck:
        """Healthy unless the last stream attempt actually failed.

        A camera that has simply never been used, or MediaMTX being briefly
        unreachable while idle, are not failures — they're reported in
        ``detail`` for observability but don't flip the agent's overall
        health, matching how ``check_plugins()`` folds every plugin's result
        into one "plugins" check.
        """
        status = self._camera_service.status()
        detail = (
            f"camera_detected={self._camera_service.check_camera_detected()} "
            f"mediamtx_reachable={self._camera_service.check_mediamtx_reachable()} "
            f"rtsp_connected={status['running']} streaming={status['running']}"
        )
        if self._camera_service.last_error:
            return PluginHealthCheck(healthy=False, detail=self._camera_service.last_error)
        return PluginHealthCheck(healthy=True, detail=detail)
