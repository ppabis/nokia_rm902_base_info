"""Loader bodies shipped with the tool (prepared offline from Care Suite FGs).

The bodies are the exact bytes BEST/Care Suite upload after their 4-byte
length.  They run from RAM; nothing is written to phone storage.
"""
import hashlib
from pathlib import Path

EXPECTED = {
    'secondary.bin': '0b894fec33888572c68a152c06469cfbb1a7a2ceb7178d0d1a4ff9ba9e923cce',
    'algorithm.bin': '81fe1d883af60cb8effc8b01ff2ed234cea65726a9fe3c673f6b669e072ab45a',
}


def load_bodies(directory) -> tuple:
    """Return (secondary, algorithm) after verifying their pinned hashes."""
    root = Path(directory)
    bodies = []
    for name, expected in EXPECTED.items():
        path = root / name
        if not path.is_file():
            raise FileNotFoundError(f'missing loader body: {path}')
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != expected:
            raise ValueError(f'{name} hash {digest} != expected {expected}')
        bodies.append(data)
    return bodies[0], bodies[1]
