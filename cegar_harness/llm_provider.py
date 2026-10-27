"""Interchangeable LLM provider interface separating Controlled Replay from Live LLM runs."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class LLMGenerationResult:
    """Result from a live LLM provider call."""

    executed: bool
    status: str  # "EXECUTED", "NOT_EXECUTED_NO_CONFIG", "EXECUTION_ERROR"
    model_name: str
    generated_code: str
    prompt_tokens: int
    completion_tokens: int
    error_message: str = ""


class LiveLLMClient:
    """Optional live OpenAI-compatible LLM client for Experiment B (Live Agent Continuation).

    Reads configuration from environment variables:
      - CEGAR_LLM_API_BASE (e.g., https://api.openai.com/v1 or http://localhost:11434/v1)
      - CEGAR_LLM_API_KEY
      - CEGAR_LLM_MODEL (e.g., gpt-4o-mini, qwen2.5-coder:7b)

    If not configured, explicitly reports `NOT_EXECUTED_NO_CONFIG` without fabricating outputs.
    """

    def __init__(
        self,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> None:
        self.api_base = (api_base or os.environ.get("CEGAR_LLM_API_BASE", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("CEGAR_LLM_API_KEY", "")
        self.model_name = model_name or os.environ.get("CEGAR_LLM_MODEL", "")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_base and self.model_name)

    def generate_patch(self, compacted_context: str, target_file: str) -> LLMGenerationResult:
        if not self.is_configured:
            return LLMGenerationResult(
                executed=False,
                status="NOT_EXECUTED_NO_CONFIG",
                model_name="none",
                generated_code="",
                prompt_tokens=0,
                completion_tokens=0,
                error_message=(
                    "Live LLM experiment not executed: CEGAR_LLM_API_BASE and CEGAR_LLM_MODEL "
                    "environment variables are not configured."
                ),
            )

        url = f"{self.api_base}/chat/completions"
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model_name,
            "temperature": 0.0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"Return ONLY valid Python code for `{target_file}` that satisfies the specification "
                        "and avoids any refuted counterexamples."
                    ),
                },
                {"role": "user", "content": compacted_context},
            ],
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                content = body["choices"][0]["message"]["content"]
                usage = body.get("usage", {})
                return LLMGenerationResult(
                    executed=True,
                    status="EXECUTED",
                    model_name=self.model_name,
                    generated_code=self._strip_markdown_fences(content),
                    prompt_tokens=int(usage.get("prompt_tokens", 0)),
                    completion_tokens=int(usage.get("completion_tokens", 0)),
                )
        except Exception as exc:
            return LLMGenerationResult(
                executed=False,
                status="EXECUTION_ERROR",
                model_name=self.model_name,
                generated_code="",
                prompt_tokens=0,
                completion_tokens=0,
                error_message=str(exc),
            )

    @staticmethod
    def _strip_markdown_fences(text: str) -> str:
        lines = text.strip().splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip() + "\n"
