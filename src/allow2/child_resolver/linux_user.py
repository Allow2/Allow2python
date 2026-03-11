from __future__ import annotations

import os
import subprocess
from typing import Any

from allow2.models import Child


def get_linux_username() -> str:
    username = os.environ.get("USER")
    if username:
        return username
    try:
        return subprocess.check_output(
            ["whoami"], text=True, timeout=5
        ).strip()
    except Exception:
        return ""


async def resolve(children: list[Child]) -> dict[str, Any] | None:
    if not children:
        return None

    username = get_linux_username()
    if not username:
        return None

    lower = username.lower()

    for child in children:
        if child.id == 0 or child.name == "__parent__":
            continue

        if child.os_username and child.os_username.lower() == lower:
            return {"child_id": child.id, "child_name": child.name}

        if child.name and child.name.lower() == lower:
            return {"child_id": child.id, "child_name": child.name}

    return None


class LinuxUserResolver:
    async def resolve(self, children: list[Child]) -> dict[str, Any] | None:
        return await resolve(children)
