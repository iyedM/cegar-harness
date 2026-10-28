"""Interchangeable LLM provider interface separating Controlled Replay from Live Multi-Turn LLM runs."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class LLMGenerationResult:
    """Result from a live LLM provider call."""

    executed: bool
    status: str  # "EXECUTED", "NOT_EXECUTED_NO_CONFIG", "EXECUTION_ERROR"
    model_name: str
    generated_code: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float = 0.0
    error_message: str = ""


class LiveLLMClient:
    """Optional live OpenAI-compatible LLM client for Experiment B (Multi-Turn Live Agent Repair Loop).

    Reads configuration from environment variables (or explicit constructor overrides):
      - CEGAR_LLM_API_BASE (e.g., https://api.openai.com/v1 or http://localhost:11434/v1)
      - CEGAR_LLM_API_KEY
      - CEGAR_LLM_MODEL (e.g., llama3:latest, qwen2.5-coder:7b, gpt-4o-mini)

    If not configured, explicitly reports `NOT_EXECUTED_NO_CONFIG` without fabricating outputs.
    """

    def __init__(
        self,
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout_seconds: float = 180.0,
    ) -> None:
        self.api_base = (api_base or os.environ.get("CEGAR_LLM_API_BASE", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("CEGAR_LLM_API_KEY", "")
        self.model_name = model_name or os.environ.get("CEGAR_LLM_MODEL", "")
        self.timeout_seconds = timeout_seconds

    @property
    def is_configured(self) -> bool:
        return bool(self.api_base and self.model_name)

    def generate_patch(
        self,
        compacted_context: str,
        target_file: str,
        repair_feedback: Optional[List[str]] = None,
    ) -> LLMGenerationResult:
        if not self.is_configured:
            return LLMGenerationResult(
                executed=False,
                status="NOT_EXECUTED_NO_CONFIG",
                model_name="none",
                generated_code="",
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=0.0,
                error_message=(
                    "Live LLM experiment not executed: CEGAR_LLM_API_BASE and CEGAR_LLM_MODEL "
                    "environment variables are not configured."
                ),
            )

        url = f"{self.api_base}/chat/completions"
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        user_prompt = compacted_context
        if repair_feedback:
            feedback_block = "\n".join(repair_feedback)
            user_prompt = (
                f"{compacted_context}\n\n"
                f"[POST-COMPACTION SELF-REPAIR FEEDBACK]\n{feedback_block}\n"
                f"Output ONLY the corrected Python source code for `{target_file}` inside a ```python ... ``` block."
            )

        payload = {
            "model": self.model_name,
            "temperature": 0.0,
            "max_tokens": 320,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"You are an autonomous Python code repair agent. Return ONLY valid, complete Python code "
                        f"for `{target_file}` enclosed in a ```python ... ``` block. Do not include explanations, "
                        "test functions, or markdown prose outside the code block."
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
        }
        t0 = time.perf_counter()
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                content = body["choices"][0]["message"]["content"]
                usage = body.get("usage", {})
                return LLMGenerationResult(
                    executed=True,
                    status="EXECUTED",
                    model_name=self.model_name,
                    generated_code=self._strip_markdown_fences(content),
                    prompt_tokens=int(usage.get("prompt_tokens", 0)),
                    completion_tokens=int(usage.get("completion_tokens", 0)),
                    latency_ms=round(elapsed_ms, 2),
                )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return LLMGenerationResult(
                executed=False,
                status="EXECUTION_ERROR",
                model_name=self.model_name,
                generated_code="",
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=round(elapsed_ms, 2),
                error_message=str(exc),
            )

    @staticmethod
    def _strip_markdown_fences(text: str) -> str:
        match = re.search(r"```(?:python|py)?\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip() + "\n"
        lines = text.strip().splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip() + "\n"

