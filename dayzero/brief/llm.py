"""Pluggable LLM backend for the decision brief.

Ollama, Groq and OpenRouter all speak the OpenAI-compatible
/v1/chat/completions shape, so they are one client with a different base_url.
Anthropic is wired separately because it is worth using if credits appear.

Configure with environment variables:

    DAYZERO_LLM=ollama|groq|openrouter|anthropic|none   (default: auto)
    DAYZERO_LLM_MODEL=<model id>                        (optional override)
    GROQ_API_KEY / OPENROUTER_API_KEY / ANTHROPIC_API_KEY

If nothing is configured, or the call fails for any reason, the deterministic
template brief is returned instead. The app never surfaces an LLM error.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache

import httpx

from . import template

# Models good enough to write a short brief from structured numbers, best
# first. Nothing is ever downloaded -- only what is already installed is used.
#
# Ollama's *cloud* models come first deliberately. They run on Ollama's
# servers, so a 31B model answers in about a second on a laptop that would
# need several minutes to run a 4B locally. Several are gated behind a paid
# plan; unavailable ones are skipped at call time rather than assumed.
OLLAMA_PREFERRED = [
    # Cloud, as named by a *local* Ollama proxying to ollama.com.
    "gemma4:31b-cloud", "qwen3.5:397b-cloud", "deepseek-v4-flash:cloud",
    "glm-5.1:cloud", "minimax-m2.7:cloud", "qwen3.5:cloud",
    # The same tier as named by the *hosted* API, which drops the suffix.
    "gemma4:31b", "glm-5.3-flash", "deepseek-v4-flash", "qwen3.5:397b",
    "nemotron-3-ultra",
    # Local fallbacks, fastest-acceptable first. Reasoning models are ranked
    # last: they spend minutes thinking before writing a word.
    "llama3.2:3b", "llama3:latest", "llama3.2:1b",
    "qwen3.5:4b", "qwen3.5:latest", "qwen3.5:2b",
]

# How many candidate models to try before giving up and using the template.
MAX_MODEL_ATTEMPTS = 3


# Ollama's own hosted endpoint. A deployed server has no local Ollama, but it
# can reach the same cloud models with an API key from ollama.com/settings/keys.
OLLAMA_CLOUD = "https://ollama.com"


def ollama_base() -> str:
    """Where to reach Ollama: the hosted API if a key is set, else localhost."""
    explicit = os.getenv("OLLAMA_HOST")
    if explicit:
        return explicit.rstrip("/")
    if os.getenv("OLLAMA_API_KEY"):
        return OLLAMA_CLOUD
    return "http://localhost:11434"


BACKENDS = {
    "ollama": {
        "base_url": None,  # resolved per call, see ollama_base()
        "model": None,  # resolved from what is actually installed
        "key_env": None,
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "key_env": "GROQ_API_KEY",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "key_env": "OPENROUTER_API_KEY",
    },
}

SYSTEM = """You are the briefing layer of DayZero, a water-resilience stress-testing engine.

You are given the numeric output of a hydrological simulation and a budget optimiser.
Write a decision brief for a city official who is not an engineer.

Hard rules:
- Every number you state must come from the input. Never invent or round-trip a figure.
- Money and volumes: quote the pre-formatted strings under "display" verbatim
  (e.g. "Rs 19.97 lakh", "2,581 ML"). Never print a raw figure like 1997000.0.
- These are scenario projections under stated assumptions, not predictions. Never
  claim to know what will happen.
- Explain WHY the recommended plan beats the naive one. That contrast is the point.
- Be direct and concrete. No hedging, no filler, no exclamation marks.

Return ONLY a JSON object with exactly these keys:
  headline       string, one sentence, the finding
  situation      string, 2-4 sentences on the baseline and what fails
  recommendation array of strings, one per funded intervention, each with its cost
  reasoning      string, 2-4 sentences on why this allocation beats ranking by cost-effectiveness
  tradeoffs      string, 2-3 sentences on what the plan does not fix and what it costs
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "situation": {"type": "string"},
        "recommendation": {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string"},
        "tradeoffs": {"type": "string"},
    },
    "required": ["headline", "situation", "recommendation", "reasoning", "tradeoffs"],
    "additionalProperties": False,
}


@lru_cache(maxsize=1)
def ollama_models() -> tuple[str, ...]:
    """Models installed in a reachable local Ollama, best-first.

    Probed once and memoised: a dead Ollama must not add a timeout to every
    request.
    """
    key = os.getenv("OLLAMA_API_KEY")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        r = httpx.get(f"{ollama_base()}/api/tags", headers=headers, timeout=4.0)
        r.raise_for_status()
        names = [m["name"] for m in r.json().get("models", [])]
    except Exception:
        # Reaching the hosted API without a listable catalogue is still usable:
        # fall back to the known-good cloud model names.
        if key:
            return tuple(n for n in OLLAMA_PREFERRED if n.endswith(("-cloud", ":cloud")))
        return ()
    ordered = [n for n in OLLAMA_PREFERRED if n in names]
    ordered += [n for n in names if n not in ordered]
    return tuple(ordered)


def resolve_model(backend: str) -> str | None:
    override = os.getenv("DAYZERO_LLM_MODEL")
    if override:
        return override
    if backend == "ollama":
        models = ollama_models()
        return models[0] if models else None
    if backend == "anthropic":
        return "claude-opus-5"
    cfg = BACKENDS.get(backend)
    return cfg["model"] if cfg else None


def active_backend() -> str:
    """Which backend will actually be used, given env and what is reachable."""
    choice = (os.getenv("DAYZERO_LLM") or "auto").lower()
    if choice == "none":
        return "none"
    if choice in BACKENDS or choice == "anthropic":
        return choice
    # auto: a hosted free tier if a key is present, else a local Ollama if one
    # is actually running, else the deterministic template.
    if os.getenv("GROQ_API_KEY"):
        return "groq"
    if os.getenv("OPENROUTER_API_KEY"):
        return "openrouter"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if ollama_models():
        return "ollama"
    return "none"


def status() -> dict:
    b = active_backend()
    return {
        "backend": b,
        "model": resolve_model(b),
        "fallback": "template",
        "ollama_models": list(ollama_models()),
    }


def _compact(payload: dict) -> dict:
    """Trim to what the model needs, and pre-format every figure it may quote.

    Two jobs. First, drop the month-by-month series: 60 data points per
    variable buys nothing and derails small models. Second, hand over
    human-readable strings alongside the raw values -- a model given
    1997000.0 will print "1997000.0 INR", but a model given "Rs 19.97 lakh"
    can only print that. Formatting is not the model's job to get right.
    """
    def slim(block: dict) -> dict:
        return {k: v for k, v in block.items() if k != "series"}

    opt = payload["optimization"]
    plan = opt["optimal"]["plan"]
    region = payload["region"]

    display = {
        "budget": template.fmt_money(opt["budget"]),
        "plan_total_cost": template.fmt_money(plan["total_cost"]),
        "rooftop_cost": template.fmt_money(plan["rwh_cost"]),
        "measures": [
            f"{m['name']} -- {template.fmt_money(m['cost'])}, "
            f"{m['months_to_deploy']} months to deploy"
            for m in plan["measures"]
        ],
        "annual_demand": template.fmt_litres(region["annual_demand_l"]),
        "harvestable_per_year": template.fmt_litres(region["harvestable_l_per_year"]),
        "unmet_no_action": template.fmt_litres(opt["baseline"]["result"]["total_unmet_l"]),
        "unmet_with_plan": template.fmt_litres(opt["optimal"]["result"]["total_unmet_l"]),
        "population": f"{region['population']:,}",
    }

    return {
        "region": region,
        "scenario": payload.get("scenario", {}),
        "baseline": slim(opt["baseline"]["result"]),
        "greedy": slim(opt["greedy"]["result"]),
        "optimal": slim(opt["optimal"]["result"]),
        "funded_plan": plan,
        "budget": opt["budget"],
        "currency": opt.get("currency", "INR"),
        "improvement": opt["improvement"],
        "bottleneck": payload.get("bottleneck"),
        "display": display,
    }


def _openai_compatible(backend: str, payload: dict) -> dict:
    from openai import OpenAI

    cfg = BACKENDS[backend]
    key_env = cfg["key_env"]
    if backend == "ollama":
        # A local Ollama ignores the key; the hosted one requires it.
        api_key = os.getenv("OLLAMA_API_KEY") or "ollama"
    else:
        api_key = os.getenv(key_env) if key_env else None
        if key_env and not api_key:
            raise RuntimeError(f"{key_env} is not set")

    base_url = (ollama_base() + "/v1") if backend == "ollama" else cfg["base_url"]
    client = OpenAI(base_url=base_url, api_key=api_key or "none", timeout=90.0)

    override = os.getenv("DAYZERO_LLM_MODEL")
    if override:
        candidates = [override]
    elif backend == "ollama":
        # Cloud models can be gated behind a paid plan and models can be
        # retired upstream; both surface only when you actually call them.
        candidates = list(ollama_models())[:MAX_MODEL_ATTEMPTS]
    else:
        candidates = [cfg["model"]]
    if not candidates:
        raise RuntimeError(f"no model available for backend {backend}")

    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps(_compact(payload), separators=(",", ":"))},
    ]

    last: Exception | None = None
    for model in candidates:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.3,
                max_tokens=1400,
                # Without this, models emit markdown-fenced prose around the JSON.
                response_format={"type": "json_object"},
                # Ollama-specific: stop reasoning models burning minutes on a
                # chain of thought before writing a two-paragraph brief.
                extra_body={"think": False} if backend == "ollama" else {},
            )
            out = _parse_json(resp.choices[0].message.content or "")
            out["_model"] = model
            return out
        except Exception as exc:
            last = exc
    raise last or RuntimeError("all candidate models failed")


def _parse_json(text: str) -> dict:
    """Recover the JSON object from a small model's reply.

    Local models routinely wrap JSON in markdown fences or emit a <think>
    block first, even in JSON mode. Rather than fail the brief over that, strip
    the noise and take the outermost object.
    """
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("no JSON object in model reply")


def _anthropic(payload: dict) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    model = os.getenv("DAYZERO_LLM_MODEL") or "claude-opus-5"
    resp = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM,
        thinking={"type": "adaptive"},
        output_config={
            "format": {"type": "json_schema", "schema": SCHEMA},
            "effort": "low",
        },
        messages=[
            {
                "role": "user",
                "content": json.dumps(_compact(payload), separators=(",", ":")),
            }
        ],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return _parse_json(text)


def generate(payload: dict) -> dict:
    """Produce a brief. Falls back to the template on any failure."""
    backend = active_backend()
    if backend == "none":
        return template.generate(payload)
    try:
        raw = _anthropic(payload) if backend == "anthropic" else _openai_compatible(backend, payload)
        brief = template.generate(payload)  # guarantees every key exists
        for key in ("headline", "situation", "reasoning", "tradeoffs"):
            if isinstance(raw.get(key), str) and raw[key].strip():
                brief[key] = raw[key].strip()
        recs = raw.get("recommendation")
        if isinstance(recs, list) and recs and all(isinstance(r, str) for r in recs):
            brief["recommendation"] = recs
        brief["source"] = backend
        brief["model"] = raw.get("_model")
        return brief
    except Exception as exc:
        out = template.generate(payload)
        out["source"] = "template"
        out["fallback_reason"] = f"{type(exc).__name__}: {exc}"[:200]
        return out
