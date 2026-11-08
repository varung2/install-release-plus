"""Provider-agnostic state management helpers.

All providers use the same cache backend (``InstallRelease.config.cache``).
This module wraps the raw cache calls so individual providers don't need to
import config directly just for persistence.
"""

from __future__ import annotations

import os

from InstallRelease.config import cache
from InstallRelease.helper.collision import binary_path
from InstallRelease.providers.git.schemas import Release


def save_state(key: str, release: Release) -> None:
    """Persist *release* under *key* and flush the cache to disk."""
    existed = key in cache.state
    previous = cache.state.get(key)
    displaced = {}
    if release.install_method == "binary" and release.install_path:
        path = os.path.abspath(release.install_path)
        directory = os.path.dirname(path)
        displaced = {
            old_key: old
            for old_key, old in cache.state.items()
            if old_key != key and binary_path(old_key, old, directory) == path
        }
        for old_key in displaced:
            cache.pop(old_key)
    cache.set(key, release)
    try:
        cache.save()
    except Exception:
        if existed:
            cache.set(key, previous)
        else:
            cache.pop(key)
        for old_key, old in displaced.items():
            cache.set(old_key, old)
        raise


def load_state(key: str) -> Release | None:
    """Return the cached ``Release`` for *key*, or ``None`` if not found."""
    return cache.get(key)
