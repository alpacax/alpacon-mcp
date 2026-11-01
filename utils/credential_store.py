"""Atomic persistence for local credential configuration files."""

import json
import os
import tempfile
from pathlib import Path


def ensure_private_directory(directory: Path) -> None:
    """Create an application-owned credential directory with owner-only access."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == 'posix':
        directory.chmod(0o700)


def save_json_securely(data: object, file_path: Path) -> None:
    """Write JSON privately and atomically, leaving the old file intact on failure.

    The temporary file is created beside the destination so os.replace stays on
    the same filesystem. Serialization and the complete file write happen before
    the destination is replaced.
    """
    file_path = Path(file_path)
    parent = file_path.parent
    parent.mkdir(parents=True, exist_ok=True)

    # Serialize first, before opening any file. A serialization error must not
    # truncate or otherwise affect the existing credentials.
    payload = json.dumps(data, indent=2)

    fd: int | None = None
    temporary_path: Path | None = None
    try:
        fd, temporary_name = tempfile.mkstemp(
            prefix=f'.{file_path.name}.', suffix='.tmp', dir=parent
        )
        temporary_path = Path(temporary_name)
        if os.name == 'posix':
            os.fchmod(fd, 0o600)

        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            fd = None
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temporary_path, file_path)
        temporary_path = None

        if os.name == 'posix':
            file_path.chmod(0o600)
            directory_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if fd is not None:
            os.close(fd)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
