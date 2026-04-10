"""
claims.py — Claim registry and convergence metrics.

Parses structured claims from agent outputs, tracks their lifecycle,
and computes convergence metrics to determine when the dialectic is done.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal


ClaimStatus = Literal["proposed", "contested", "accepted", "withdrawn", "refined"]


@dataclass
class ClaimHistory:
    round: int
    action: str
    agent: str
    reason: str = ""
    revision: str = ""


@dataclass
class Claim:
    claim_id: str
    statement: str
    proposer: str          # "α" or "β"
    status: ClaimStatus = "proposed"
    confidence_α: float = 0.0
    confidence_β: float = 0.0
    evidence: list[str] = field(default_factory=list)
    counterevidence: list[str] = field(default_factory=list)
    history: list[ClaimHistory] = field(default_factory=list)

    def confidence_gap(self) -> float:
        return abs(self.confidence_α - self.confidence_β)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


CONFIDENCE_MAP = {"HIGH": 0.90, "MEDIUM": 0.65, "LOW": 0.30}


def _parse_confidence(text: str) -> float:
    text = text.upper().strip()
    if text in CONFIDENCE_MAP:
        return CONFIDENCE_MAP[text]
    try:
        return float(text)
    except ValueError:
        return 0.5


def parse_claims_from_output(output: str, agent_name: str, round_num: int) -> list[Claim]:
    """
    Parse the Claims Registry section from an agent's output.

    Handles two agent output formats:
      Format A (structured): "- claim_id: α_001 / statement: ..."
      Format B (bold header): "**α_001**: statement text" or "- **β_001**: statement"
    """
    claims: list[Claim] = []

    # Find the Claims Registry section
    registry_match = re.search(
        r"## Claims Registry\s*(.*?)(?=^##|\Z)",
        output,
        re.DOTALL | re.MULTILINE,
    )
    if not registry_match:
        return claims

    registry_text = registry_match.group(1)

    # ---- Format B: **α_001**: statement  (what agents actually produce) ----
    # Matches: optional "- " then **id**: rest-of-line
    format_b_re = re.compile(
        r"[-*\s]*\*\*([A-Za-zα-ωΑ-Ω_][A-Za-zα-ωΑ-Ω_0-9]*)\*\*\s*:\s*(.+?)(?=\n[-*\s]*\*\*[A-Za-zα-ωΑ-Ω]|\Z)",
        re.DOTALL,
    )
    format_b_matches = list(format_b_re.finditer(registry_text))

    if format_b_matches:
        for m in format_b_matches:
            raw_id = m.group(1).strip()
            rest = m.group(2).strip()

            # Statement is the first line of rest
            lines = rest.splitlines()
            statement = lines[0].strip().rstrip(".")

            # Scan following lines for confidence/evidence
            block = "\n".join(lines[1:]) if len(lines) > 1 else ""
            confidence_m = re.search(r"confidence\s*:\s*(\S+)", block, re.IGNORECASE)
            evidence_m = re.search(r"evidence\s*:\s*\[([^\]]*)\]", block, re.IGNORECASE)

            confidence = _parse_confidence(confidence_m.group(1)) if confidence_m else 0.5
            evidence = []
            if evidence_m:
                evidence = [e.strip() for e in evidence_m.group(1).split(",") if e.strip()]

            # Normalise claim id to include agent prefix if missing
            claim_id = raw_id
            if not any(claim_id.startswith(p) for p in ("α_", "β_", "alpha_", "beta_")):
                claim_id = f"{agent_name}_{claim_id}"

            hist = ClaimHistory(round=round_num, action=f"proposed_by_{agent_name}", agent=agent_name)
            claim = Claim(
                claim_id=claim_id,
                statement=statement,
                proposer=agent_name,
                status="proposed",
                evidence=evidence,
                history=[hist],
            )
            if agent_name == "α":
                claim.confidence_α = confidence
            else:
                claim.confidence_β = confidence
            claims.append(claim)
        return claims

    # ---- Format A (original structured format, fallback) ----
    claim_blocks = re.split(r"(?=[-*]\s*claim_id:)", registry_text)

    for block in claim_blocks:
        if not block.strip():
            continue

        claim_id_m = re.search(r"claim_id:\s*(\S+)", block)
        statement_m = re.search(r"statement:\s*(.+?)(?:\n|$)", block)
        confidence_m = re.search(r"confidence:\s*(\S+)", block)
        evidence_m = re.search(r"evidence:\s*\[([^\]]*)\]", block)

        if not (claim_id_m and statement_m):
            continue

        claim_id = claim_id_m.group(1).strip()
        statement = statement_m.group(1).strip()
        confidence = _parse_confidence(confidence_m.group(1)) if confidence_m else 0.5
        evidence = []
        if evidence_m:
            evidence = [e.strip() for e in evidence_m.group(1).split(",") if e.strip()]

        hist = ClaimHistory(round=round_num, action=f"proposed_by_{agent_name}", agent=agent_name)
        claim = Claim(
            claim_id=claim_id,
            statement=statement,
            proposer=agent_name,
            status="proposed",
            evidence=evidence,
            history=[hist],
        )
        if agent_name == "α":
            claim.confidence_α = confidence
        else:
            claim.confidence_β = confidence

        claims.append(claim)

    return claims


@dataclass
class ConvergenceMetrics:
    accepted_ratio: float
    contested_ratio: float
    withdrawn_ratio: float
    confidence_gap: float
    new_claims: int
    delta_from_last: float
    total_claims: int

    @property
    def converged(self) -> bool:
        return (
            self.total_claims > 0
            and self.accepted_ratio > 0.85
            and self.confidence_gap < 0.15
            and self.new_claims == 0
            and self.delta_from_last < 0.02
        )

    def summary(self) -> str:
        status = "CONVERGED" if self.converged else "ongoing"
        return (
            f"[convergence/{status}] "
            f"accepted={self.accepted_ratio:.2f} "
            f"contested={self.contested_ratio:.2f} "
            f"withdrawn={self.withdrawn_ratio:.2f} "
            f"gap={self.confidence_gap:.2f} "
            f"new={self.new_claims} "
            f"delta={self.delta_from_last:.3f} "
            f"total={self.total_claims}"
        )


class ClaimRegistry:
    def __init__(self):
        self._claims: dict[str, Claim] = {}
        self._prior_accepted_ratio: float = 0.0

    def update_from_round(
        self,
        α_output: str,
        β_output: str,
        α_revision: str,
        β_revision: str,
        round_num: int,
    ):
        """Parse and integrate claims from a full round."""
        new_count = 0

        for text, agent in [
            (α_output, "α"),
            (β_output, "β"),
            (α_revision, "α"),
            (β_revision, "β"),
        ]:
            for claim in parse_claims_from_output(text, agent, round_num):
                if claim.claim_id not in self._claims:
                    self._claims[claim.claim_id] = claim
                    new_count += 1
                else:
                    existing = self._claims[claim.claim_id]
                    # Update confidence
                    if agent == "α":
                        existing.confidence_α = claim.confidence_α
                    else:
                        existing.confidence_β = claim.confidence_β
                    existing.history.extend(claim.history)

        # Update statuses based on confidence convergence
        self._update_statuses(round_num)
        return new_count

    def _update_statuses(self, round_num: int):
        for claim in self._claims.values():
            gap = claim.confidence_gap()
            avg = (claim.confidence_α + claim.confidence_β) / 2
            if avg > 0.70 and gap < 0.20:
                if claim.status != "accepted":
                    claim.status = "accepted"
                    claim.history.append(ClaimHistory(
                        round=round_num, action="accepted", agent="both"
                    ))
            elif avg < 0.25:
                if claim.status != "withdrawn":
                    claim.status = "withdrawn"
                    claim.history.append(ClaimHistory(
                        round=round_num, action="withdrawn", agent="both"
                    ))
            elif claim.confidence_α > 0 and claim.confidence_β > 0 and gap > 0.30:
                if claim.status not in ("contested", "accepted", "withdrawn"):
                    claim.status = "contested"
                    claim.history.append(ClaimHistory(
                        round=round_num, action="contested", agent="both"
                    ))

    def convergence_metrics(self, new_claims_this_round: int = 0) -> ConvergenceMetrics:
        total = len(self._claims)
        if total == 0:
            return ConvergenceMetrics(0, 0, 0, 0, 0, 0, 0)

        accepted = sum(1 for c in self._claims.values() if c.status == "accepted")
        contested = sum(1 for c in self._claims.values() if c.status == "contested")
        withdrawn = sum(1 for c in self._claims.values() if c.status == "withdrawn")

        accepted_ratio = accepted / total
        contested_ratio = contested / total
        withdrawn_ratio = withdrawn / total

        accepted_claims = [c for c in self._claims.values() if c.status == "accepted"]
        if accepted_claims:
            avg_gap = sum(c.confidence_gap() for c in accepted_claims) / len(accepted_claims)
        else:
            avg_gap = 1.0

        delta = abs(accepted_ratio - self._prior_accepted_ratio)
        self._prior_accepted_ratio = accepted_ratio

        return ConvergenceMetrics(
            accepted_ratio=accepted_ratio,
            contested_ratio=contested_ratio,
            withdrawn_ratio=withdrawn_ratio,
            confidence_gap=avg_gap,
            new_claims=new_claims_this_round,
            delta_from_last=delta,
            total_claims=total,
        )

    def get_by_status(self, status: ClaimStatus) -> list[Claim]:
        return [c for c in self._claims.values() if c.status == status]

    def save(self, path: str):
        claims_list = [c.to_dict() for c in self._claims.values()]
        Path(path).write_text(
            "\n".join(json.dumps(c) for c in claims_list)
        )

    def load(self, path: str):
        p = Path(path)
        if not p.exists():
            return
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            claim = Claim(
                claim_id=d["claim_id"],
                statement=d["statement"],
                proposer=d["proposer"],
                status=d["status"],
                confidence_α=d["confidence_α"],
                confidence_β=d["confidence_β"],
                evidence=d["evidence"],
                counterevidence=d["counterevidence"],
                history=[ClaimHistory(**h) for h in d["history"]],
            )
            self._claims[claim.claim_id] = claim
