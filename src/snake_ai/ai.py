"""Provider-independent System One decisions and durable per-session JSONL records."""
import json
import math
import os
from dataclasses import dataclass, field
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

from .engine import DIRECTIONS, OPPOSITE


@dataclass(frozen=True)
class AISettings:
    provider: str
    model: str
    base_url: str
    api_key: str = field(default="", repr=False)

    @classmethod
    def from_env(cls):
        provider = os.getenv("AI_PROVIDER", "ollama").strip().lower()
        if provider == "ollama":
            return cls(provider, os.getenv("LOCAL_AI_MODEL_NAME", "tev1:4b-mlx-bf16").strip(),
                       os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip())
        if provider == "openrouter":
            return cls(provider, os.getenv("OPENROUTER_MODEL_NAME", "typesafe/jev-1.14").strip(),
                       os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api").strip(),
                       os.getenv("OPENROUTER_API_KEY", "").strip())
        raise ValueError("AI_PROVIDER must be ollama or openrouter")

    def validate(self):
        if not self.model:
            raise ValueError("Set LOCAL_AI_MODEL_NAME or OPENROUTER_MODEL_NAME for the selected provider")
        if self.provider == "openrouter" and not self.api_key:
            raise ValueError("Set OPENROUTER_API_KEY in .env to use OpenRouter")


class SessionLog:
    def __init__(self, directory):
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.path = Path(directory) / f"ai-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}.jsonl"
        self.lock = threading.Lock()

    def write(self, event, **fields):
        record = {"timestamp": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
        with self.lock, self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, allow_nan=False) + "\n")
            stream.flush()


def payload(model, state):
    return {"model": model, "state": state, "questions": {"move": {
        "type": "choice",
        "instructions": "Choose the next arrow key to keep the snake alive and collect food. "
        "One key moves one cell. Immediate reversal is impossible; the opposite direction is excluded. "
        "Walls and the snake body are fatal. The tail vacates its cell unless food is eaten. "
        "Prefer a move that avoids trapping the snake. Choose only from the supplied options. Allowed directions can still be fatal."
        + (" This is a benchmark: reach food_target before move_limit. When food is empty, keep moving safely; "
           "the pending_food appears after its cell becomes free. Food order never skips."
           if "benchmark" in state else ""),
        "criteria": {name: f"Press {name}: delta x={delta[0]}, delta y={delta[1]}"
                     for name, delta in DIRECTIONS.items()
                     if name != OPPOSITE[state["direction"]]}}}}


def choose_move(response, allowed_directions):
    probabilities = response["answers"]["move"]["probabilities"]
    if set(probabilities) != set(allowed_directions):
        raise ValueError("Model must return probabilities for exactly the supplied arrow keys")
    if any(isinstance(p, bool) or not isinstance(p, (int, float)) or
           not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities.values()):
        raise ValueError("Invalid move probabilities")
    return max(allowed_directions, key=lambda key: probabilities[key])


def decide(model, state, base_url, timeout, log, *, provider="ollama", api_key=""):
    settings = AISettings(provider, model, base_url, api_key)
    if provider not in ("ollama", "openrouter"):
        raise ValueError("AI_PROVIDER must be ollama or openrouter")
    settings.validate()
    request_body = payload(model, state)
    endpoint = base_url.rstrip("/") + "/v1/systemone"
    log.write("request", step=state["step"], endpoint=endpoint, provider=provider, payload=request_body)
    start = time.monotonic()
    try:
        headers = {"Content-Type": "application/json"}
        if provider == "openrouter":
            headers["Authorization"] = "Bearer " + api_key
        request = Request(endpoint, data=json.dumps(request_body).encode(), headers=headers)
        with urlopen(request, timeout=timeout) as result:
            raw = result.read().decode("utf-8")
        log.write("response", step=state["step"], provider=provider, raw=raw.replace(api_key, "[REDACTED]") if api_key else raw,
                  elapsed_seconds=time.monotonic() - start)
        return choose_move(json.loads(raw), request_body["questions"]["move"]["criteria"])
    except Exception as exc:
        message = str(exc).replace(api_key, "[REDACTED]") if api_key else str(exc)
        log.write("error", step=state["step"], provider=provider, error=message,
                  elapsed_seconds=time.monotonic() - start)
        raise RuntimeError(message) from None
