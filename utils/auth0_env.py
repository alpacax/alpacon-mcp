"""Auth0 setting names shared by JWT validation and the OAuth proxy."""

import os
from threading import Lock

from utils.logger import get_logger

logger = get_logger('auth0_env')

_LEGACY_NAMES = {
    'AUTH0_ALPACON_DOMAIN': 'AUTH0_DOMAIN',
    'AUTH0_ALPACON_LOGIN_CLIENT_ID': 'AUTH0_CLIENT_ID',
    'AUTH0_ALPACON_LOGIN_CLIENT_SECRET': 'AUTH0_CLIENT_SECRET',
    'AUTH0_ALPACON_USER_AUDIENCE': 'AUTH0_AUDIENCE',
    'AUTH0_ALPACON_MFA_AUDIENCE': 'AUTH0_MFA_AUDIENCE',
    'AUTH0_ALPACON_NAMESPACE': 'AUTH0_NAMESPACE',
}
_warned_legacy_names: set[str] = set()
_warning_lock = Lock()


def get_auth0_env(name: str, default: str = '') -> str:
    """Prefer the target name, preserving explicitly empty environment values."""
    value = os.getenv(name)
    if value is not None:
        return value

    legacy_name = _LEGACY_NAMES[name]
    value = os.getenv(legacy_name)
    if value is None:
        return default

    with _warning_lock:
        if legacy_name not in _warned_legacy_names:
            _warned_legacy_names.add(legacy_name)
            logger.warning(
                '%s is deprecated; use %s instead. '
                'The legacy name will be removed in a later release.',
                legacy_name,
                name,
            )
    return value
