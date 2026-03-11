from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from LinuxAgent.log import get_logger


logger = get_logger("Agent.docker_sandbox")


class DockerSandbox:
    def __init__(
        self,
        *,
        image: str | None = None,
        workspace_host: str | Path | None = None,
    ) -> None:
        self._image = image or (os.getenv("CHELP_DOCKER_IMAGE") or "ubuntu:22.04")
        self._workspace_host = Path(workspace_host).resolve() if workspace_host is not None else Path.cwd().resolve()
        self._client: Any | None = None
        self._container: Any | None = None

    @property
    def image(self) -> str:
        return self._image

    @property
    def workspace_host(self) -> Path:
        return self._workspace_host

    def ensure_started(self) -> None:
        if self._container is not None:
            return
        try:
            import docker
        except Exception as e:
            raise RuntimeError("docker SDK 未安装，请安装依赖：pip install docker") from e

        self._client = docker.from_env()
        try:
            self._client.ping()
        except Exception as e:
            raise RuntimeError("Docker Engine 不可用，请确认已启动 Docker Desktop/daemon") from e

        logger.info("sandbox start image=%s workspace=%s", self._image, self._workspace_host)
        volumes = {
            str(self._workspace_host): {
                "bind": "/workspace",
                "mode": os.getenv("CHELP_DOCKER_WORKSPACE_MODE") or "ro",
            }
        }
        self._container = self._client.containers.run(
            self._image,
            command=["bash", "-lc", "sleep infinity"],
            detach=True,
            tty=True,
            volumes=volumes,
            working_dir="/workspace",
        )

    def exec(self, *, command: str) -> tuple[int, str, str]:
        self.ensure_started()
        if self._container is None:
            return 1, "", "sandbox not started"
        logger.info("sandbox exec cmd=%s", (command or "")[:200])
        res = self._container.exec_run(
            ["bash", "-lc", command],
            workdir="/workspace",
            demux=True,
        )
        exit_code = int(getattr(res, "exit_code", 1) or 0)
        out = getattr(res, "output", None)
        stdout_b = b""
        stderr_b = b""
        if isinstance(out, tuple) and len(out) == 2:
            stdout_b = out[0] or b""
            stderr_b = out[1] or b""
        elif isinstance(out, (bytes, bytearray)):
            stdout_b = bytes(out)
        stdout = stdout_b.decode("utf-8", errors="replace") if stdout_b else ""
        stderr = stderr_b.decode("utf-8", errors="replace") if stderr_b else ""
        return exit_code, stdout, stderr

    def close(self) -> None:
        if self._container is None:
            return
        try:
            cid = getattr(self._container, "id", None)
            logger.info("sandbox stop id=%s", cid)
        except Exception:
            pass
        try:
            self._container.remove(force=True)
        except Exception:
            pass
        self._container = None

