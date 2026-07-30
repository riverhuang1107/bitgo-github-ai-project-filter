from __future__ import annotations

from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


def ensure_vps_ssh_public_key(path: Path) -> tuple[str, bool]:
    """Load a local Ed25519 SSH key or create one with owner-only permissions.

    The private key remains in the user configuration directory.  Only its
    OpenSSH public-key representation is returned to the VPS API.
    """
    if path.exists():
        private_key = serialization.load_ssh_private_key(path.read_bytes(), password=None)
        if not isinstance(private_key, ed25519.Ed25519PrivateKey):
            raise TypeError(f"VPS SSH key is not an Ed25519 private key: {path}")
        created = False
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        private_key = ed25519.Ed25519PrivateKey.generate()
        path.write_bytes(
            private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.OpenSSH,
                serialization.NoEncryption(),
            )
        )
        try:
            path.chmod(0o600)
        except OSError:
            pass
        created = True
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.OpenSSH,
        serialization.PublicFormat.OpenSSH,
    ).decode("ascii")
    return f"{public_key} github-ai-daily-vps-check", created
