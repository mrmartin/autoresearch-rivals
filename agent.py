"""
agent.py — Agent abstraction wrapping any LLM provider via OpenRouter.

All calls go through OpenRouter using the OpenAI-compatible API.
The OpenRouter key is passed via config or OPENROUTER_API_KEY env var.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL_ALPHA = "anthropic/claude-opus-4"
DEFAULT_MODEL_BETA = "openai/gpt-4o"


@dataclass
class AgentConfig:
    name: str                   # "α" or "β"
    model: str                  # OpenRouter model string
    program_path: str           # path to program_*.md
    api_key: str = ""           # OpenRouter API key
    temperature: float = 0.7
    max_tokens: int = 4096

    def __post_init__(self):
        if not self.api_key:
            self.api_key = os.environ.get("OPENROUTER_API_KEY", "")


@dataclass
class AgentStats:
    tokens_in: int = 0
    tokens_out: int = 0
    calls: int = 0
    cost_usd: float = 0.0


class Agent:
    def __init__(self, config: AgentConfig, retriever):
        self.config = config
        self.retriever = retriever
        self.program = Path(config.program_path).read_text()
        self.stats = AgentStats()

    # ------------------------------------------------------------------
    # Core LLM call
    # ------------------------------------------------------------------

    def _call(self, messages: list[dict], instruction: str | None = None) -> str:
        """Make an OpenRouter API call and return the assistant's response."""
        if instruction:
            messages = messages + [{"role": "user", "content": instruction}]

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/autoresearch-rivals",
            "X-Title": "autoresearch-rivals",
        }

        payload = {
            "model": self.config.model,
            "messages": [{"role": "system", "content": self.program}] + messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

        for attempt in range(3):
            try:
                resp = requests.post(
                    f"{OPENROUTER_BASE_URL}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=120,
                )
                resp.raise_for_status()
                data = resp.json()

                # Track usage
                usage = data.get("usage", {})
                self.stats.tokens_in += usage.get("prompt_tokens", 0)
                self.stats.tokens_out += usage.get("completion_tokens", 0)
                self.stats.calls += 1

                return data["choices"][0]["message"]["content"]

            except requests.exceptions.Timeout:
                print(f"[agent-{self.config.name}] Timeout (attempt {attempt+1}/3), retrying...")
                time.sleep(5 * (attempt + 1))
            except requests.exceptions.HTTPError as e:
                if resp.status_code == 429:
                    wait = 30 * (attempt + 1)
                    print(f"[agent-{self.config.name}] Rate limited, waiting {wait}s...")
                    time.sleep(wait)
                else:
                    raise
            except Exception as e:
                if attempt == 2:
                    raise
                print(f"[agent-{self.config.name}] Error: {e}, retrying...")
                time.sleep(10)

        raise RuntimeError(f"Agent {self.config.name} failed after 3 attempts")

    # ------------------------------------------------------------------
    # Query extraction (for retrieval)
    # ------------------------------------------------------------------

    def _extract_queries(self, topic: str, prior_context: str | None) -> list[str]:
        """Ask the model to generate targeted search queries for the math corpus."""
        sources_info = ""
        if hasattr(self.retriever, "sources_summary"):
            sources_info = (
                "\n\nThe corpus contains these sources:\n"
                + self.retriever.sources_summary()
                + "\nWrite queries that would find the most relevant theorems, proofs, "
                  "and definitions across these specific books."
            )

        context_note = ""
        if prior_context:
            preview = prior_context[:800] + "..." if len(prior_context) > 800 else prior_context
            context_note = f"\n\nYour prior research (summary):\n{preview}"

        prompt = (
            f"Research topic:\n{topic}{sources_info}{context_note}\n\n"
            "Generate 8 specific search queries to retrieve the most relevant passages "
            "from the mathematical corpus. Make queries precise and technical — use "
            "exact theorem names, author names, and formal terms where possible.\n"
            "Output as a JSON array of strings, nothing else.\n"
            'Example: ["Cook-Reckhow theorem proof systems", '
            '"Krajicek Pudlak bounded arithmetic S2", ...]'
        )
        raw = self._call([], instruction=prompt)
        try:
            start = raw.find("[")
            end = raw.rfind("]") + 1
            queries = json.loads(raw[start:end])
            return [str(q) for q in queries[:8]]
        except Exception:
            lines = [l.strip().strip('"').strip("'").strip("-").strip() for l in raw.splitlines()]
            return [l for l in lines if l][:8]

    # ------------------------------------------------------------------
    # The three phases
    # ------------------------------------------------------------------

    def research(self, topic: str, prior_context: str | None = None) -> str:
        """Phase 1: Produce independent research output."""
        queries = self._extract_queries(topic, prior_context)
        chunks = self.retriever.retrieve_multi(queries, k=15)
        corpus_context = self.retriever.format_context(chunks)

        context_section = ""
        if prior_context:
            context_section = (
                f"\n\n## Your Prior Research (from last round)\n\n{prior_context}"
            )

        messages = [
            {
                "role": "user",
                "content": (
                    f"## Research Topic\n\n{topic}\n\n"
                    f"{corpus_context}"
                    f"{context_section}\n\n"
                    "Produce your research output following the format in your instructions. "
                    "Be rigorous, cite corpus chunks where relevant, and structure your claims clearly."
                ),
            }
        ]
        return self._call(messages)

    def critique(self, rival_output: str) -> str:
        """Phase 2: Critique the rival agent's output."""
        messages = [
            {
                "role": "user",
                "content": (
                    "A rival research group has produced the following analysis. "
                    "Find every flaw, gap, and questionable claim. "
                    "Be rigorous and specific. Quote the passages you critique.\n\n"
                    "---\n\n"
                    f"{rival_output}"
                ),
            }
        ]
        return self._call(messages)

    def revise(self, own_output: str, critique_of_own: str) -> str:
        """Phase 3: Revise own output in response to critique."""
        messages = [
            {
                "role": "user",
                "content": (
                    "The following objections have been raised against your research. "
                    "Address each one: CONCEDE (if correct), REBUT (with evidence), "
                    "or REFINE (strengthen/narrow the claim). "
                    "Produce your complete revised output.\n\n"
                    "## Your Original Output\n\n"
                    f"{own_output}\n\n"
                    "## Critique Raised Against You\n\n"
                    f"{critique_of_own}"
                ),
            }
        ]
        return self._call(messages)
