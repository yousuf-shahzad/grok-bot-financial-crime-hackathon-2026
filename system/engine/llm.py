"""Minimal LLM client for the cross-examiner (owner: Yousuf's Claude). Standard library only.

Provider order, decided from the environment at call time:
  1. OPENROUTER_API_KEY -> https://openrouter.ai/api/v1/chat/completions, model OPENROUTER_MODEL
     (default x-ai/grok-4.20). The organisers set this key when they test.
  2. XAI_API_KEY        -> https://api.x.ai/v1/chat/completions, model XAI_MODEL
     (default grok-4.20-0309-non-reasoning). Our own Grok key while building.
  3. neither            -> available() is False and the system runs on rules alone.
LLM_DISABLE=1 turns it off whatever keys are present.

For local runs a .env file at the repo root is read if it exists (it is gitignored and is never
part of the submission). Keys are never logged. Every call uses temperature 0 and a strict JSON
schema, retries twice, and returns None on any failure so callers fall back to the rules.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Optional

_ENV_LOADED = False
_LOCK = threading.Lock()
_MEMO = {}
STATS = {"calls": 0, "ok": 0, "failed": 0, "cached": 0, "seconds": 0.0}


def _load_dotenv() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(root, ".env")
    if not os.path.isfile(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and v and k not in os.environ:
                    os.environ[k] = v
    except OSError:
        pass


def provider() -> Optional[dict]:
    _load_dotenv()
    if os.environ.get("LLM_DISABLE") == "1":
        return None
    if os.environ.get("OPENROUTER_API_KEY"):
        return {"name": "openrouter", "url": "https://openrouter.ai/api/v1/chat/completions",
                "key": os.environ["OPENROUTER_API_KEY"],
                "model": os.environ.get("OPENROUTER_MODEL", "x-ai/grok-4.20")}
    if os.environ.get("XAI_API_KEY"):
        return {"name": "xai", "url": "https://api.x.ai/v1/chat/completions",
                "key": os.environ["XAI_API_KEY"],
                "model": os.environ.get("XAI_MODEL", "grok-4.20-0309-non-reasoning")}
    return None


def available() -> bool:
    return provider() is not None


def describe() -> str:
    p = provider()
    return "rules only (no LLM key)" if p is None else "%s / %s" % (p["name"], p["model"])


def ask_json(system: str, user: str, schema: dict, name: str = "answer", timeout: float = 45.0) -> Optional[dict]:
    """One chat completion constrained to `schema`. Returns the parsed object or None."""
    p = provider()
    if p is None:
        return None
    key = hashlib.sha256(json.dumps([p["model"], system, user, schema], sort_keys=True).encode("utf-8")).hexdigest()
    with _LOCK:
        if key in _MEMO:
            STATS["cached"] += 1
            return _MEMO[key]
    body = {
        "model": p["model"],
        "temperature": 0,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}},
    }
    data = json.dumps(body).encode("utf-8")
    headers = {"Authorization": "Bearer " + p["key"], "Content-Type": "application/json"}
    if p["name"] == "openrouter":
        headers["X-Title"] = "track2-crossexam"
    result = None
    t0 = time.time()
    for attempt in range(3):
        with _LOCK:
            STATS["calls"] += 1
        try:
            req = urllib.request.Request(p["url"], data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            if isinstance(content, list):  # some providers return content parts
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
            result = json.loads(content)
            break
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403, 404):  # bad request, key or model: retrying will not help
                break
            time.sleep(1.5 * (attempt + 1))
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    with _LOCK:
        STATS["seconds"] += time.time() - t0
        STATS["ok" if result is not None else "failed"] += 1
        _MEMO[key] = result
    return result
