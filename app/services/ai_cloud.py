"""The online AI service the author connected, and the record of what was sent to it (DECISIONS D-061).

* The service and the author's API key are kept in the system keychain; the key goes only to
  that service. Nothing is connected until the author pastes a key.
* Before anything is sent, the author is shown exactly what will go: ``preview`` gives the text
  and a fingerprint of it. The send must name that fingerprint, so if the story, the model or
  the service changed in between, nothing is sent and the author is shown the new text first.
* Every send is written to ``ai-sent.jsonl`` in the data folder before it goes: when, to which
  service and model, and the full text. The key is never written there.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from provenance_core.providers.cloud_ai import PROVIDERS, CloudAIError, CloudModel

SECRET = "cloud_ai"  # in the system keychain: {"provider": …, "url": …, "key": …}
LOG = "ai-sent.jsonl"
LOG_SHOWN = 50

model_factory = CloudModel  # tests put a fake service here


def settings(keystore) -> dict | None:
    raw = keystore.load_secret(SECRET)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get("key") and data.get("provider") in PROVIDERS else None


def open_model(keystore, model: str = "") -> CloudModel:
    s = settings(keystore)
    if s is None:
        raise CloudAIError("connect an online AI service first")
    return model_factory(s["provider"], s["key"], model, s.get("url", ""))


def describe(keystore) -> dict:
    """What the page shows about the connection (never the key)."""
    s = settings(keystore)
    if s is None:
        return {"connected": False}
    m = model_factory(s["provider"], s["key"], "", s.get("url", ""))
    return {"connected": True, "provider": s["provider"], "service": m.service, "host": m.host,
            "default_model": PROVIDERS[s["provider"]]["model"]}


def connect(keystore, provider: str, key: str, url: str = "") -> list[str]:
    """Check the key by asking the service for its models; keep it only if that works."""
    m = model_factory(provider, key, "", url)
    models = m.models()
    keystore.save_secret(SECRET, json.dumps({"provider": provider, "url": m.base if provider == "other" else "",
                                             "key": m.key}))
    return models


def forget(keystore) -> None:
    keystore.save_secret(SECRET, "")


def fingerprint(m: CloudModel, system: str, user: str) -> str:
    """What exactly would be sent, and where to: if any of it changes, so does this."""
    blob = json.dumps([m.provider, m.base, m.model, system, user], ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def write_log(data_dir: Path, m: CloudModel, system: str, user: str, *, title: str, space: str) -> None:
    entry = {
        "time": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "service": m.service, "host": m.host,
        "model": m.model, "title": title, "space": space, "characters": len(system) + len(user),
        "fingerprint": fingerprint(m, system, user), "system": system, "user": user,
    }
    with (Path(data_dir) / LOG).open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_log(data_dir: Path, limit: int = LOG_SHOWN) -> dict:
    """The most recent sends, newest first, and how many there were in all."""
    try:
        lines = (Path(data_dir) / LOG).read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return {"count": len(entries), "entries": entries[::-1][:limit]}
