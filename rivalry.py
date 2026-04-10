"""
rivalry.py — Orchestrator for the adversarial dual-agent research dialectic.

Usage:
    python rivalry.py \\
        --topic topic.md \\
        --corpus corpus/index/ \\
        --model-alpha anthropic/claude-opus-4 \\
        --model-beta openai/gpt-4o \\
        --max-rounds 8

    # With explicit OpenRouter key:
    python rivalry.py --topic topic.md --api-key sk-or-v1-...

    # Resume an interrupted run:
    python rivalry.py --topic topic.md --resume

Environment variables:
    OPENROUTER_API_KEY   OpenRouter API key (alternative to --api-key)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from agent import Agent, AgentConfig, DEFAULT_MODEL_ALPHA, DEFAULT_MODEL_BETA
from claims import ClaimRegistry, ConvergenceMetrics
from retrieve import load_retriever
from synthesis import synthesize

console = Console()

OPENROUTER_API_KEY = "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"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_round_file(round_dir: Path, filename: str, content: str):
    round_dir.mkdir(parents=True, exist_ok=True)
    (round_dir / filename).write_text(content)


def _load_round_file(round_dir: Path, filename: str) -> str | None:
    p = round_dir / filename
    return p.read_text() if p.exists() else None


def _log_results(results_path: Path, round_num: int, metrics: ConvergenceMetrics,
                 α_tokens: int, β_tokens: int):
    header = [
        "round", "accepted_ratio", "contested_ratio", "withdrawn_ratio",
        "confidence_gap", "new_claims", "delta", "total_claims",
        "α_tokens_in", "α_tokens_out", "β_tokens_in", "β_tokens_out",
    ]
    row = [
        round_num,
        f"{metrics.accepted_ratio:.4f}",
        f"{metrics.contested_ratio:.4f}",
        f"{metrics.withdrawn_ratio:.4f}",
        f"{metrics.confidence_gap:.4f}",
        metrics.new_claims,
        f"{metrics.delta_from_last:.4f}",
        metrics.total_claims,
        α_tokens, 0,  # we track total in/out in stats
        β_tokens, 0,
    ]
    write_header = not results_path.exists()
    with open(results_path, "a", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        if write_header:
            writer.writerow(header)
        writer.writerow(row)


# ---------------------------------------------------------------------------
# Context window management
# ---------------------------------------------------------------------------

def _summarize_prior(text: str, max_chars: int = 6000) -> str:
    """Truncate old context to avoid blowing out context windows."""
    if len(text) <= max_chars:
        return text
    # Keep the claims registry section if present
    claims_idx = text.find("## Claims Registry")
    if claims_idx > 0:
        preamble = text[:max_chars // 2]
        claims_section = text[claims_idx:]
        return f"{preamble}\n\n[... prior prose truncated for context management ...]\n\n{claims_section}"
    return text[:max_chars] + "\n\n[... truncated ...]"


# ---------------------------------------------------------------------------
# Rivalry orchestrator
# ---------------------------------------------------------------------------

class Rivalry:
    def __init__(
        self,
        topic_path: str,
        corpus_path: str,
        agent_α_config: AgentConfig,
        agent_β_config: AgentConfig,
        max_rounds: int = 10,
        convergence_threshold: float = 0.85,
        output_dir: str = ".",
    ):
        self.topic = Path(topic_path).read_text()
        self.corpus_path = corpus_path
        self.max_rounds = max_rounds
        self.convergence_threshold = convergence_threshold
        self.output_dir = Path(output_dir)
        self.rounds_dir = self.output_dir / "rounds"
        self.results_path = self.output_dir / "results.tsv"

        console.print(f"[bold blue]Loading retriever from {corpus_path}...[/bold blue]")
        retriever = load_retriever(corpus_path)

        self.agent_α = Agent(agent_α_config, retriever)
        self.agent_β = Agent(agent_β_config, retriever)

        self.claim_registry = ClaimRegistry()
        self.round = 0

        # Contexts carry over between rounds
        self.context_α: str | None = None
        self.context_β: str | None = None

    def _run_round(self, round_num: int):
        round_dir = self.rounds_dir / f"round_{round_num:03d}"

        console.rule(f"[bold yellow]Round {round_num}[/bold yellow]")

        # Phase 1: Independent research
        console.print("[cyan]Phase 1 — Independent research[/cyan]")

        with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as p:
            t1 = p.add_task("Agent α researching...", total=None)
            α_output = self.agent_α.research(self.topic, self.context_α)
            p.update(t1, description="Agent α done")

            t2 = p.add_task("Agent β researching...", total=None)
            β_output = self.agent_β.research(self.topic, self.context_β)
            p.update(t2, description="Agent β done")

        _write_round_file(round_dir, "α_output.md", α_output)
        _write_round_file(round_dir, "β_output.md", β_output)

        # Phase 2: Adversarial critique
        console.print("[cyan]Phase 2 — Adversarial critique[/cyan]")

        with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as p:
            t1 = p.add_task("Agent α critiquing β...", total=None)
            α_critique = self.agent_α.critique(β_output)
            p.update(t1, description="α critique done")

            t2 = p.add_task("Agent β critiquing α...", total=None)
            β_critique = self.agent_β.critique(α_output)
            p.update(t2, description="β critique done")

        _write_round_file(round_dir, "α_critique.md", α_critique)
        _write_round_file(round_dir, "β_critique.md", β_critique)

        # Phase 3: Revision under fire
        console.print("[cyan]Phase 3 — Revision under fire[/cyan]")

        with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as p:
            t1 = p.add_task("Agent α revising...", total=None)
            α_revision = self.agent_α.revise(α_output, β_critique)
            p.update(t1, description="α revision done")

            t2 = p.add_task("Agent β revising...", total=None)
            β_revision = self.agent_β.revise(β_output, α_critique)
            p.update(t2, description="β revision done")

        _write_round_file(round_dir, "α_revision.md", α_revision)
        _write_round_file(round_dir, "β_revision.md", β_revision)

        # Phase 4: Convergence check
        console.print("[cyan]Phase 4 — Convergence check[/cyan]")

        new_claims = self.claim_registry.update_from_round(
            α_output, β_output, α_revision, β_revision, round_num
        )
        metrics = self.claim_registry.convergence_metrics(new_claims)

        # Save claims state
        self.claim_registry.save(str(self.output_dir / "workspace_α" / "claims.jsonl"))
        self.claim_registry.save(str(self.output_dir / "workspace_β" / "claims.jsonl"))

        # Save diff summary
        diff = {
            "round": round_num,
            "new_claims": new_claims,
            "metrics": {
                "accepted_ratio": metrics.accepted_ratio,
                "contested_ratio": metrics.contested_ratio,
                "withdrawn_ratio": metrics.withdrawn_ratio,
                "confidence_gap": metrics.confidence_gap,
                "delta_from_last": metrics.delta_from_last,
                "converged": metrics.converged,
            },
        }
        _write_round_file(round_dir, "diff.json", json.dumps(diff, indent=2))

        # Log to results.tsv
        _log_results(
            self.results_path, round_num, metrics,
            self.agent_α.stats.tokens_in,
            self.agent_β.stats.tokens_in,
        )

        console.print(Panel(metrics.summary(), title="Convergence", style="green" if metrics.converged else "yellow"))

        # Carry revised outputs to next round (with context compression)
        self.context_α = _summarize_prior(α_revision)
        self.context_β = _summarize_prior(β_revision)

        # Save workspace drafts
        (self.output_dir / "workspace_α" / "draft.md").write_text(α_revision)
        (self.output_dir / "workspace_β" / "draft.md").write_text(β_revision)

        return metrics

    def run(self) -> str:
        console.print(Panel(
            f"[bold]autoresearch-rivals[/bold]\n\n"
            f"α model: {self.agent_α.config.model}\n"
            f"β model: {self.agent_β.config.model}\n"
            f"Max rounds: {self.max_rounds}\n"
            f"Convergence threshold: {self.convergence_threshold}",
            title="Starting Rivalry",
            style="blue",
        ))
        console.print(f"\n[bold]Topic:[/bold]\n{self.topic[:500]}...\n" if len(self.topic) > 500 else f"\n[bold]Topic:[/bold]\n{self.topic}\n")

        for round_num in range(self.round, self.max_rounds):
            self.round = round_num
            metrics = self._run_round(round_num)

            if metrics.converged:
                console.print(f"\n[bold green]Convergence reached after round {round_num}![/bold green]")
                break

            if round_num < self.max_rounds - 1:
                console.print(f"[dim]Continuing to round {round_num + 1}...[/dim]\n")

        # Synthesis
        console.print("\n[bold blue]Synthesizing final consensus...[/bold blue]")
        consensus_text, provenance = synthesize(
            self.claim_registry,
            self.topic,
            self.round + 1,
            output_dir=str(self.output_dir),
        )

        console.print(Panel(
            f"Rounds completed: {self.round + 1}\n"
            f"Total α calls: {self.agent_α.stats.calls}\n"
            f"Total β calls: {self.agent_β.stats.calls}\n"
            f"Total α tokens: {self.agent_α.stats.tokens_in + self.agent_α.stats.tokens_out:,}\n"
            f"Total β tokens: {self.agent_β.stats.tokens_in + self.agent_β.stats.tokens_out:,}\n"
            f"\nOutputs: consensus.md, provenance.json, results.tsv",
            title="[bold green]Rivalry Complete[/bold green]",
            style="green",
        ))

        return consensus_text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run adversarial dual-agent research rivalry",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--topic", default="topic.md", help="Path to topic.md")
    parser.add_argument("--corpus", default="corpus/index", help="Path to FAISS index dir")
    parser.add_argument(
        "--model-alpha", default=DEFAULT_MODEL_ALPHA,
        help=f"OpenRouter model for agent α (default: {DEFAULT_MODEL_ALPHA})",
    )
    parser.add_argument(
        "--model-beta", default=DEFAULT_MODEL_BETA,
        help=f"OpenRouter model for agent β (default: {DEFAULT_MODEL_BETA})",
    )
    parser.add_argument(
        "--program-alpha", default="program_α.md",
        help="Path to agent α program file",
    )
    parser.add_argument(
        "--program-beta", default="program_β.md",
        help="Path to agent β program file",
    )
    parser.add_argument("--max-rounds", type=int, default=8)
    parser.add_argument("--convergence-threshold", type=float, default=0.85)
    parser.add_argument(
        "--api-key",
        default=OPENROUTER_API_KEY,
        help="OpenRouter API key (default: built-in key)",
    )
    parser.add_argument("--output-dir", default=".", help="Output directory")
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume from last completed round (not yet implemented)",
    )

    args = parser.parse_args()

    # Resolve API key
    api_key = args.api_key or os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        console.print("[red]Error: No OpenRouter API key. Pass --api-key or set OPENROUTER_API_KEY.[/red]")
        sys.exit(1)

    # Check required files
    for path, desc in [
        (args.topic, "topic file"),
        (args.program_alpha, "agent α program"),
        (args.program_beta, "agent β program"),
    ]:
        if not Path(path).exists():
            console.print(f"[red]Error: {desc} not found: {path}[/red]")
            sys.exit(1)

    # Ensure workspace dirs exist
    output_dir = Path(args.output_dir)
    (output_dir / "workspace_α").mkdir(parents=True, exist_ok=True)
    (output_dir / "workspace_β").mkdir(parents=True, exist_ok=True)
    (output_dir / "rounds").mkdir(parents=True, exist_ok=True)

    α_config = AgentConfig(
        name="α",
        model=args.model_alpha,
        program_path=args.program_alpha,
        api_key=api_key,
    )
    β_config = AgentConfig(
        name="β",
        model=args.model_beta,
        program_path=args.program_beta,
        api_key=api_key,
    )

    rivalry = Rivalry(
        topic_path=args.topic,
        corpus_path=args.corpus,
        agent_α_config=α_config,
        agent_β_config=β_config,
        max_rounds=args.max_rounds,
        convergence_threshold=args.convergence_threshold,
        output_dir=args.output_dir,
    )

    try:
        rivalry.run()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted. Partial results saved to rounds/ and workspaces.[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    main()
