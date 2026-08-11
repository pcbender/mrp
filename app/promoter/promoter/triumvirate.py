"""
Stages 2 and 3 of keyword generation: three vendors vote, consensus decides.

The models are given the gated candidates from `evidence.py` and may only judge
them — keep, drop, or rephrase. They cannot add a term, so a single model's
invention can never reach the channel. Cross-vendor agreement then filters what
one model would have kept on its own: a keyword needs KEEP_QUORUM of the three.

Each vendor answers under a schema, so a malformed ballot is a provider error
rather than something to parse defensively.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from .config import (
    ANTHROPIC_API_KEY,
    GOOGLE_API_KEY,
    OPENAI_API_KEY,
    TRIUMVIRATE,
)

_PROMPTS_DIR = Path(__file__).parent / "prompts"

KEEP_QUORUM = 2
PHRASING_QUORUM = 2

BALLOT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "votes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "candidate": {"type": "string"},
                    "keep": {"type": "boolean"},
                    "phrasing": {"type": "string"},
                },
                "required": ["candidate", "keep", "phrasing"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["votes"],
    "additionalProperties": False,
}


class BallotError(RuntimeError):
    """One vendor failed to return a usable ballot."""


# --- vendor adapters ---------------------------------------------------------

def _openapi_subset(schema: Any) -> Any:
    """Gemini's response_schema is an OpenAPI subset — it rejects the
    `additionalProperties` that OpenAI's strict mode requires."""
    if isinstance(schema, dict):
        return {
            key: _openapi_subset(value)
            for key, value in schema.items()
            if key != "additionalProperties"
        }
    if isinstance(schema, list):
        return [_openapi_subset(item) for item in schema]
    return schema


def _ask_gemini(system: str, user: str, model: str) -> list[dict[str, Any]]:
    if not GOOGLE_API_KEY:
        raise BallotError("GOOGLE_SERVICE_API_KEY not set")
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GOOGLE_API_KEY)
    response = client.models.generate_content(
        model=model,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=_openapi_subset(BALLOT_SCHEMA),
        ),
        contents=user,
    )
    return _votes(response.text)


def _ask_claude(system: str, user: str, model: str) -> list[dict[str, Any]]:
    if not ANTHROPIC_API_KEY:
        raise BallotError("ANTHROPIC_API_KEY not set")
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    # Opus 5 thinks by default and max_tokens covers thinking plus the reply,
    # so this needs headroom well past the ballot's own size.
    response = client.messages.create(
        model=model,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": BALLOT_SCHEMA}},
    )
    if response.stop_reason == "refusal":
        raise BallotError("claude declined the request")
    text = next((b.text for b in response.content if b.type == "text"), "")
    return _votes(text)


def _ask_openai(system: str, user: str, model: str) -> list[dict[str, Any]]:
    if not OPENAI_API_KEY:
        raise BallotError("OPENAI_API_KEY not set")
    import openai

    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "ballot", "strict": True, "schema": BALLOT_SCHEMA},
        },
    )
    return _votes(response.choices[0].message.content)


ADAPTERS: dict[str, Callable[[str, str, str], list[dict[str, Any]]]] = {
    "gemini": _ask_gemini,
    "claude": _ask_claude,
    "openai": _ask_openai,
}


def _votes(raw: str | None) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw or "")
    except json.JSONDecodeError as exc:
        raise BallotError(f"ballot was not JSON: {str(raw)[:200]}") from exc
    votes = payload.get("votes") if isinstance(payload, dict) else payload
    if not isinstance(votes, list):
        raise BallotError(f"ballot had no votes array: {str(raw)[:200]}")
    return [v for v in votes if isinstance(v, dict)]


# --- ballots and consensus ---------------------------------------------------

def build_prompt(artist: dict[str, Any], lines: list[str]) -> tuple[str, str]:
    """Return (system, user) for the ballot. `lines` are 'term — evidence'."""
    artist_name = artist.get("name", "")
    system = (_PROMPTS_DIR / "ballot_system.md").read_text().replace(
        "{artist_name}", artist_name
    )

    parts = [f"Artist: {artist_name}", f"Type: {artist.get('type') or 'solo artist'}"]
    bio = artist.get("bio_long") or artist.get("bio_short")
    if bio:
        parts.append(f"Bio:\n{bio}")
    parts.append("Candidates:\n" + "\n".join(f"- {line}" for line in lines))
    return system, "\n\n".join(parts)


def collect_ballots(
    artist: dict[str, Any],
    lines: list[str],
    seats: tuple[tuple[str, str], ...] = TRIUMVIRATE,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    """Ask every seat in parallel. Returns (ballots, errors) keyed by vendor.

    One vendor failing is survivable — consensus only needs a quorum — so
    errors are collected rather than raised.
    """
    system, user = build_prompt(artist, lines)
    ballots: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}

    def run(seat: tuple[str, str]) -> None:
        vendor, model = seat
        try:
            ballots[vendor] = ADAPTERS[vendor](system, user, model)
        except Exception as exc:  # noqa: BLE001 — any vendor failure is just a lost seat
            errors[vendor] = f"{type(exc).__name__}: {exc}"[:300]

    with ThreadPoolExecutor(max_workers=len(seats)) as pool:
        list(pool.map(run, seats))

    return ballots, errors


def consensus(
    terms: list[str],
    ballots: dict[str, list[dict[str, Any]]],
    keep_quorum: int = KEEP_QUORUM,
    phrasing_quorum: int = PHRASING_QUORUM,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Tally the ballots.

    A term survives on `keep_quorum` keeps. Its wording changes only when
    `phrasing_quorum` vendors independently proposed the same rewrite —
    otherwise the evidence-derived term stands. Votes naming a term that was
    not on the ballot are discarded, which is what stops a model inventing one.

    Returns (kept terms in ballot order, per-term tally for auditing).
    """
    index = {term.casefold(): term for term in terms}
    keeps: dict[str, list[str]] = {term.casefold(): [] for term in terms}
    rewrites: dict[str, dict[str, list[str]]] = {term.casefold(): {} for term in terms}

    for vendor, votes in sorted(ballots.items()):
        seen: set[str] = set()
        for vote in votes:
            key = " ".join(str(vote.get("candidate") or "").split()).casefold()
            if key not in index or key in seen:
                continue  # unknown or duplicate — a model cannot add candidates
            seen.add(key)
            if not vote.get("keep"):
                continue
            keeps[key].append(vendor)

            phrasing = " ".join(str(vote.get("phrasing") or "").split())
            if phrasing and phrasing.casefold() != key:
                rewrites[key].setdefault(phrasing.casefold(), []).append(vendor)

    kept: list[str] = []
    tally: list[dict[str, Any]] = []
    for term in terms:
        key = term.casefold()
        voters = keeps[key]
        winner, backers = term, []
        if len(voters) >= keep_quorum:
            for _, supporters in sorted(
                rewrites[key].items(), key=lambda kv: (-len(kv[1]), kv[0])
            ):
                if len(supporters) >= phrasing_quorum:
                    backers = supporters
                    break
            if backers:
                winner = _spelling(rewrites, key, backers, ballots)
            kept.append(winner)

        tally.append({
            "term": term,
            "keeps": voters,
            "kept": len(voters) >= keep_quorum,
            "final": winner if len(voters) >= keep_quorum else None,
            "rephrased_by": backers,
        })

    return kept, tally


def _spelling(
    rewrites: dict[str, dict[str, list[str]]],
    key: str,
    backers: list[str],
    ballots: dict[str, list[dict[str, Any]]],
) -> str:
    """Recover the winning rewrite's casing from its first backer's ballot.

    Backers are recorded in sorted vendor order, so when two vendors agree on a
    rewrite but differ on capitalisation the earlier vendor's spelling wins.
    Arbitrary, but deterministic — the same ballots always yield the same word.
    """
    target = next(
        folded for folded, supporters in rewrites[key].items() if supporters == backers
    )
    for vendor in backers:
        for vote in ballots.get(vendor, []):
            phrasing = " ".join(str(vote.get("phrasing") or "").split())
            if phrasing.casefold() == target:
                return phrasing
    return target
