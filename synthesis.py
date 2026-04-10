"""
synthesis.py — Final consensus document generation.

Takes the ClaimRegistry after the dialectic completes and produces:
- consensus.md: structured synthesis of accepted/contested/withdrawn claims
- provenance.json: who proposed what, who killed what
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from claims import ClaimRegistry, Claim


def _format_claim_section(claims: list[Claim], title: str) -> str:
    if not claims:
        return f"## {title}\n\n*None.*\n\n"

    lines = [f"## {title}\n"]
    for claim in claims:
        lines.append(f"### {claim.claim_id}: {claim.statement}")
        lines.append(f"- **Proposer**: Agent {claim.proposer}")
        lines.append(f"- **Confidence α**: {claim.confidence_α:.2f}")
        lines.append(f"- **Confidence β**: {claim.confidence_β:.2f}")
        if claim.evidence:
            lines.append(f"- **Evidence**: {', '.join(claim.evidence)}")
        if claim.counterevidence:
            lines.append(f"- **Counter-evidence**: {', '.join(claim.counterevidence)}")
        lines.append("")

    return "\n".join(lines) + "\n"


def _format_provenance(registry: ClaimRegistry) -> dict:
    provenance = {
        "generated": datetime.utcnow().isoformat() + "Z",
        "claims": {},
    }

    by_status = {
        "accepted": registry.get_by_status("accepted"),
        "contested": registry.get_by_status("contested"),
        "withdrawn": registry.get_by_status("withdrawn"),
        "proposed": registry.get_by_status("proposed"),
        "refined": registry.get_by_status("refined"),
    }

    for status, claims in by_status.items():
        for claim in claims:
            provenance["claims"][claim.claim_id] = {
                "statement": claim.statement,
                "status": status,
                "proposer": claim.proposer,
                "confidence_α": claim.confidence_α,
                "confidence_β": claim.confidence_β,
                "evidence": claim.evidence,
                "history": [
                    {
                        "round": h.round,
                        "action": h.action,
                        "agent": h.agent,
                        "reason": h.reason,
                    }
                    for h in claim.history
                ],
            }

    return provenance


def synthesize(
    registry: ClaimRegistry,
    topic: str,
    rounds_completed: int,
    output_dir: str = ".",
) -> tuple[str, dict]:
    """
    Produce consensus.md and provenance.json.
    Returns (consensus_text, provenance_dict).
    """
    accepted = registry.get_by_status("accepted")
    contested = registry.get_by_status("contested")
    withdrawn = registry.get_by_status("withdrawn")

    metrics = registry.convergence_metrics()

    # Build consensus.md
    sections = [
        f"# Consensus Document\n",
        f"*Generated after {rounds_completed} round(s) of adversarial dialectic*\n",
        f"*Convergence: accepted={metrics.accepted_ratio:.0%}, "
        f"contested={metrics.contested_ratio:.0%}, "
        f"withdrawn={metrics.withdrawn_ratio:.0%}*\n",
        f"\n## Research Question\n\n{topic}\n\n---\n\n",
        _format_claim_section(accepted, "Consensus Findings"),
        _format_claim_section(contested, "Unresolved Disputes"),
        _format_claim_section(withdrawn, "Retracted Claims"),
        (
            "## Notes on Retracted Claims\n\n"
            "Claims in the 'Retracted Claims' section were proposed but "
            "did not survive adversarial scrutiny. This is a research output: "
            "knowing what is *not* true is as valuable as knowing what is.\n\n"
        ),
    ]

    consensus_text = "\n".join(sections)

    output_path = Path(output_dir)
    (output_path / "consensus.md").write_text(consensus_text)

    provenance = _format_provenance(registry)
    (output_path / "provenance.json").write_text(
        json.dumps(provenance, indent=2)
    )

    return consensus_text, provenance
