"""The agent's cryptographic identity: an Ed25519 key that never leaves the machine."""

import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from auren_agent.signing import b64url_encode

KEY_FILE = "identity.key"
MACHINE_FILE = "machine_id"
_PRIVATE_MODE = 0o600
_GROUP_OTHER_BITS = stat.S_IRWXG | stat.S_IRWXO


class IdentityError(Exception):
    """The key or machine id on disk is missing, unreadable or unsafe."""


@dataclass(frozen=True, slots=True)
class Identity:
    private_key: Ed25519PrivateKey

    @property
    def public_key_b64(self) -> str:
        raw = self.private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return b64url_encode(raw)


def load_or_create_identity(state_dir: Path) -> Identity:
    """Load the key, creating it (mode 0600, directory 0700) on first use."""
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    key_path = state_dir / KEY_FILE
    if not key_path.exists():
        key = Ed25519PrivateKey.generate()
        seed = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _PRIVATE_MODE)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(seed)
        return Identity(key)
    if key_path.stat().st_mode & _GROUP_OTHER_BITS:
        raise IdentityError(f"{key_path} must not be accessible by group or others (chmod 600)")
    seed = key_path.read_bytes()
    try:
        return Identity(Ed25519PrivateKey.from_private_bytes(seed))
    except ValueError as exc:
        raise IdentityError(f"{key_path} is not a valid Ed25519 key") from exc


def save_machine_id(state_dir: Path, machine_id: uuid.UUID) -> None:
    (state_dir / MACHINE_FILE).write_text(f"{machine_id}\n", encoding="utf-8")


def load_machine_id(state_dir: Path) -> uuid.UUID:
    try:
        return uuid.UUID((state_dir / MACHINE_FILE).read_text(encoding="utf-8").strip())
    except (OSError, ValueError) as exc:
        raise IdentityError("this machine is not enrolled yet (run `enroll` first)") from exc
