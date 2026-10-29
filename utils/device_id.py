"""The device id the identity provider's login action keys a person's MFA record on;
stdio keeps one per installation in a file beside the token config."""

import os
import re
import secrets
from pathlib import Path

from utils.logger import get_logger
from utils.token_manager import get_token_manager

logger = get_logger('device_id')

# Mirrors the login action's validator; anything else falls back to a
# fingerprint-keyed MFA record there.
DEVICE_ID_PATTERN = re.compile(r'^[A-Za-z0-9-]{8,64}$')

DEVICE_ID_FILE = 'device_id'


def is_device_id(value: str) -> bool:
    """Whether the login action will honor this as a client-supplied device id."""
    return bool(DEVICE_ID_PATTERN.match(value.strip()))


def mint_device_id() -> str:
    """A random id; 32 hex characters clear the login action's validator."""
    return secrets.token_hex(16)


def installation_device_id(config_dir: Path | None = None) -> str:
    """This installation's id, minted once and kept beside the token config (it
    survives token changes); an unwritable directory yields an unpersisted id."""
    directory = config_dir or get_token_manager().config_dir
    path = directory / DEVICE_ID_FILE
    try:
        stored = path.read_text().strip()
    except OSError:
        stored = ''
    if is_device_id(stored):
        return stored

    device_id = mint_device_id()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(device_id + '\n')
    except OSError as e:
        logger.warning('Could not persist the device id at %s: %s', path, e)
    return device_id
