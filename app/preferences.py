"""The author's interface choices that outlive one browser tab (DECISIONS D-046).

Kept in ``<data folder>/preferences.json`` rather than in a database, so the desktop app can
read the language for its menu before any server is running, and the practice space shares it.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from pathlib import Path

from app.i18n import LANGS

FILE = "preferences.json"
_listeners: list[Callable[[dict], None]] = []


def on_change(listener: Callable[[dict], None]) -> None:
    """Called with the new preferences after each save (the desktop app relabels its menu)."""
    _listeners.append(listener)


def load(data_dir: Path) -> dict:
    try:
        data = json.loads((data_dir / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(data_dir: Path, **changes) -> dict:
    prefs = load(data_dir)
    prefs.update(changes)
    tmp = data_dir / (FILE + ".tmp")
    tmp.write_text(json.dumps(prefs, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, data_dir / FILE)
    for listener in list(_listeners):
        try:
            listener(prefs)
        except Exception:  # noqa: BLE001 - a menu that fails to relabel must not fail the request
            logging.getLogger("rprov").exception("preferences listener failed")
    return prefs


def language(data_dir: Path) -> str | None:
    value = load(data_dir).get("language")
    return value if value in LANGS else None
