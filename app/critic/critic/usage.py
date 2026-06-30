"""
API usage tracker — accumulates token counts and rate-limit state across a
batch run, surfaces warnings before limits are hit, and prints a summary.

Usage (automatic when batch/album pipeline run):
    from .usage import tracker, call_claude, record_gemini

    response = call_claude(client, model=..., max_tokens=..., ...)
    record_gemini(gemini_response)
    tracker.summary()         # print at end of run
    tracker.reset()           # call at start of each fresh run
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import anthropic


class UsageTracker:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.anthropic_calls: int = 0
        self.anthropic_input_tokens: int = 0
        self.anthropic_output_tokens: int = 0
        self.gemini_calls: int = 0
        self.gemini_input_tokens: int = 0
        self.gemini_output_tokens: int = 0
        # Rate limit state from most recent Anthropic response headers
        self._tokens_remaining: int | None = None
        self._tokens_limit: int | None = None
        self._tokens_reset: str | None = None          # ISO-8601 timestamp
        self._requests_remaining: int | None = None
        self._requests_limit: int | None = None

    # ── Anthropic ─────────────────────────────────────────────────────────────

    def record_anthropic(self, usage: Any, headers: dict[str, str] | None = None) -> None:
        if usage:
            self.anthropic_input_tokens += getattr(usage, "input_tokens", 0)
            self.anthropic_output_tokens += getattr(usage, "output_tokens", 0)
        self.anthropic_calls += 1

        if headers:
            def _int(key: str) -> int | None:
                v = headers.get(key)
                try:
                    return int(v) if v is not None else None
                except (ValueError, TypeError):
                    return None

            self._tokens_remaining = _int("anthropic-ratelimit-tokens-remaining")
            self._tokens_limit = _int("anthropic-ratelimit-tokens-limit")
            self._tokens_reset = headers.get("anthropic-ratelimit-tokens-reset")
            self._requests_remaining = _int("anthropic-ratelimit-requests-remaining")
            self._requests_limit = _int("anthropic-ratelimit-requests-limit")

    # ── Gemini ────────────────────────────────────────────────────────────────

    def record_gemini(self, usage_metadata: Any) -> None:
        if usage_metadata:
            self.gemini_input_tokens += getattr(usage_metadata, "prompt_token_count", 0) or 0
            self.gemini_output_tokens += getattr(usage_metadata, "candidates_token_count", 0) or 0
        self.gemini_calls += 1

    # ── Rate-limit guard ──────────────────────────────────────────────────────

    def check_and_maybe_pause(self, warn_pct: float = 0.20, pause_pct: float = 0.05) -> None:
        """
        After each Anthropic call:
        - warn_pct  (default 20%): print a warning
        - pause_pct (default  5%): sleep until the reset window
        """
        if self._tokens_remaining is None or self._tokens_limit is None:
            return
        pct = self._tokens_remaining / self._tokens_limit
        if pct <= pause_pct:
            reset_in = self._seconds_until_reset()
            sleep_s = max(reset_in + 2, 5)
            print(
                f"\n  ⏸  Anthropic rate limit critical: {self._tokens_remaining:,}/"
                f"{self._tokens_limit:,} tokens remaining ({pct:.0%}). "
                f"Sleeping {sleep_s}s until reset…"
            )
            time.sleep(sleep_s)
        elif pct <= warn_pct:
            print(
                f"  ⚠  Anthropic rate limit: {self._tokens_remaining:,}/"
                f"{self._tokens_limit:,} tokens remaining ({pct:.0%})"
                + (f" — resets at {self._tokens_reset}" if self._tokens_reset else "")
            )

    def _seconds_until_reset(self) -> float:
        if not self._tokens_reset:
            return 60.0
        try:
            reset_dt = datetime.fromisoformat(self._tokens_reset.rstrip("Z")).replace(
                tzinfo=timezone.utc
            )
            return max(0.0, (reset_dt - datetime.now(timezone.utc)).total_seconds())
        except ValueError:
            return 60.0

    # ── Summary ───────────────────────────────────────────────────────────────

    def summary(self) -> str:
        lines = ["", "─" * 52, "  API Usage Summary", "─" * 52]

        if self.anthropic_calls:
            total = self.anthropic_input_tokens + self.anthropic_output_tokens
            lines.append(
                f"  Anthropic : {self.anthropic_calls} call(s)  "
                f"{self.anthropic_input_tokens:,} in + {self.anthropic_output_tokens:,} out "
                f"= {total:,} tokens"
            )
            if self._tokens_remaining is not None and self._tokens_limit is not None:
                pct = self._tokens_remaining / self._tokens_limit
                lines.append(
                    f"  Rate limit: {self._tokens_remaining:,}/{self._tokens_limit:,} "
                    f"tokens remaining ({pct:.0%})"
                    + (f"  reset {self._tokens_reset}" if self._tokens_reset else "")
                )
            if self._requests_remaining is not None and self._requests_limit is not None:
                lines.append(
                    f"             {self._requests_remaining}/{self._requests_limit} "
                    "requests remaining"
                )

        if self.gemini_calls:
            total = self.gemini_input_tokens + self.gemini_output_tokens
            lines.append(
                f"  Gemini    : {self.gemini_calls} call(s)  "
                f"{self.gemini_input_tokens:,} in + {self.gemini_output_tokens:,} out "
                f"= {total:,} tokens"
            )

        lines.append("─" * 52)
        return "\n".join(lines)

    def print_summary(self) -> None:
        print(self.summary())


# Module-level singleton shared across the pipeline
tracker = UsageTracker()


def call_claude(client: anthropic.Anthropic, **kwargs: Any) -> Any:
    """
    Drop-in replacement for client.messages.create() that also records
    token usage and rate-limit headers into the module-level tracker.
    """
    raw = client.messages.with_raw_response.create(**kwargs)
    response = raw.parse()
    tracker.record_anthropic(response.usage, dict(raw.headers))
    tracker.check_and_maybe_pause()
    return response


def record_gemini(response: Any) -> None:
    """Record token usage from a Gemini response into the module-level tracker."""
    tracker.record_gemini(getattr(response, "usage_metadata", None))
