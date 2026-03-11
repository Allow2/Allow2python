from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CredentialBackend(Protocol):
    async def store(self, data: dict[str, Any]) -> None: ...
    async def load(self) -> dict[str, Any] | None: ...
    async def clear(self) -> None: ...
    async def load_last_used(self) -> dict[str, str]: ...
    async def update_last_used(self, child_id: int) -> None: ...


async def create_backend(
    backend_type: str = "plaintext",
    **kwargs: Any,
) -> CredentialBackend:
    if backend_type == "plaintext":
        from allow2.credentials.plaintext import PlaintextBackend
        return PlaintextBackend(**kwargs)

    if backend_type == "keyring":
        try:
            from allow2.credentials.keyring_backend import KeyringBackend
        except ImportError:
            raise ImportError(
                "keyring backend requires the 'keyring' package. "
                "Install it with: pip install allow2[keyring]"
            ) from None
        return KeyringBackend(**kwargs)

    raise ValueError(f"Unknown credential backend type: {backend_type}")
