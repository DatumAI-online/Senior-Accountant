"""
Generalized wrapper around the Anthropic Claude API, shared by every agent.

Extracted from the original single-purpose classify() call in
app/services/claude_service.py (kept, now implemented on top of this
client for backward compatibility) so that each agent's Skill only needs
to supply a system prompt, a skill name/version, and a list of message
content blocks. The API-call plumbing, defensive JSON extraction, typed
error handling, and call-duration timing are shared across all of them.

skill_name/skill_version are stamped onto the returned ClaudeSkillResult so
callers can record them on a ToolInvocation row — this is what makes an
AI-generated conclusion traceable to "model + version" and "prompt/Skill
version" per DATUM_AI_BOOKKEEPING_TEAM_PLAN.md Section 15.
"""

import json
import logging
import re
import time
from dataclasses import dataclass

import anthropic
from anthropic import APIConnectionError, APIStatusError, APITimeoutError

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class ClaudeSkillError(Exception):
    """Raised when a Claude Skill call fails or returns unusable output."""


@dataclass
class ClaudeSkillResult:
    data: dict
    raw_text: str
    model: str
    skill_name: str
    skill_version: str
    duration_ms: int


class ClaudeSkillClient:
    """One instance per Skill. Construct with the Skill's system prompt and
    version; call .call(content_blocks) per invocation."""

    def __init__(
        self,
        *,
        skill_name: str,
        skill_version: str,
        system_prompt: str,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        settings = get_settings()
        if not settings.anthropic_api_key:
            logger.warning("ANTHROPIC_API_KEY is not set. Requests to Claude will fail.")
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = model or settings.claude_model
        self._max_tokens = max_tokens or settings.claude_max_tokens
        self.skill_name = skill_name
        self.skill_version = skill_version
        self._system_prompt = system_prompt

    @staticmethod
    def _extract_json(raw_text: str) -> dict:
        """Defensively extract a JSON object from Claude's raw text output,
        even if the model wraps it in markdown fences or adds stray prose."""
        text = raw_text.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fenced:
            text = fenced.group(1)

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            brace_match = re.search(r"\{.*\}", text, re.DOTALL)
            if brace_match:
                try:
                    return json.loads(brace_match.group(0))
                except json.JSONDecodeError:
                    pass
            raise ClaudeSkillError(f"Could not parse JSON from Claude response: {exc}") from exc

    def call(self, content_blocks: list[dict]) -> ClaudeSkillResult:
        """content_blocks: a list of Anthropic Messages API content blocks
        (text / image / document) forming a single user turn. Returns the
        parsed JSON payload plus call metadata. Raises ClaudeSkillError on
        any API failure or unparseable output — callers must not persist
        anything on that path, only raise/escalate."""
        started = time.monotonic()
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=self._system_prompt,
                messages=[{"role": "user", "content": content_blocks}],
            )
        except APITimeoutError as exc:
            raise ClaudeSkillError("Claude API request timed out.") from exc
        except APIConnectionError as exc:
            raise ClaudeSkillError("Could not connect to Claude API.") from exc
        except APIStatusError as exc:
            raise ClaudeSkillError(
                f"Claude API returned an error status {exc.status_code}: {exc.message}"
            ) from exc

        duration_ms = int((time.monotonic() - started) * 1000)

        text_blocks = [
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ]
        raw_text = "".join(text_blocks).strip()
        if not raw_text:
            raise ClaudeSkillError("Claude returned an empty response.")

        parsed = self._extract_json(raw_text)

        return ClaudeSkillResult(
            data=parsed,
            raw_text=raw_text,
            model=self._model,
            skill_name=self.skill_name,
            skill_version=self.skill_version,
            duration_ms=duration_ms,
        )
