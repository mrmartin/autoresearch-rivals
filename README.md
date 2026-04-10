# autoresearch-rivals

*Fork of [karpathy/autoresearch](https://github.com/karpathy/autoresearch)*

An adversarial dual-agent research system. Two AI agents — a Constructivist and a Skeptic — argue about a research question until they converge on a consensus.

The core insight: the cancer patient who got their medical records analyzed by two different AI systems, framing each model's output as a "competing hypothesis to be attacked", not a conclusion to defer to. This is adversarial peer review running at machine speed.

---

## Quick Start

```bash
# Install dependencies
pip install -e .

# (Optional) Ingest a corpus of PDFs
python ingest.py corpus/raw/ --output corpus/index/

# Edit the research question
$EDITOR topic.md

# Run the rivalry (uses built-in OpenRouter key)
python rivalry.py --topic topic.md --max-rounds 4

# Read the output
cat consensus.md
cat provenance.json
```

---

## How It Works

Each round has four phases:

**Phase 1 — Independent Research**
Both agents retrieve from the shared corpus and produce independent analyses. No cross-contamination.

**Phase 2 — Adversarial Critique**
Each agent receives the other's output, framed as: *"A rival research group has produced this. Find every flaw."*

**Phase 3 — Revision Under Fire**
Each agent receives the critique of its own work and must address every objection: concede, rebut, or refine.

**Phase 4 — Convergence Check**
The orchestrator parses structured claims from both outputs, updates the claim registry, and checks whether the dialectic has converged (>85% of claims accepted by both agents, confidence gap < 15%, no new claims).

---

## Architecture

```
rivalry.py          Orchestrator — runs the dialectic loop
├── agent.py        Agent abstraction (wraps OpenRouter API)
├── retrieve.py     RAG retrieval (shared index, both agents)
├── claims.py       Claim registry + convergence metrics
└── synthesis.py    Final consensus document generation

ingest.py           Corpus → chunks → FAISS index

program_α.md        Agent α: The Constructivist (builds arguments)
program_β.md        Agent β: The Skeptic (finds counterexamples)
topic.md            Research question, scope, success criteria

corpus/
├── raw/            Original PDFs/text files
├── processed/      Extracted text
└── index/          FAISS index + chunk metadata

workspace_α/        Agent α scratch space (draft.md, claims.jsonl)
workspace_β/        Agent β scratch space
rounds/             Full dialectic history (one dir per round)
consensus.md        Final merged output
provenance.json     Who proposed what, who killed what
results.tsv         Per-round convergence metrics
```

---

## Agent Models

By default:
- Agent α (Constructivist): `anthropic/claude-opus-4`
- Agent β (Skeptic): `openai/gpt-4o`

Override with `--model-alpha` and `--model-beta`. Any [OpenRouter model](https://openrouter.ai/models) works.

The power of using different providers: Claude and GPT have genuinely different systematic biases from training. Same model twice would still share failure modes.

---

## CLI Reference

```
python rivalry.py [OPTIONS]

Options:
  --topic PATH            Research topic file (default: topic.md)
  --corpus PATH           FAISS index directory (default: corpus/index)
  --model-alpha MODEL     OpenRouter model for agent α
  --model-beta MODEL      OpenRouter model for agent β  
  --program-alpha PATH    Agent α program/instructions file
  --program-beta PATH     Agent β program/instructions file
  --max-rounds N          Maximum dialectic rounds (default: 8)
  --convergence-threshold F  Convergence cutoff (default: 0.85)
  --api-key KEY           OpenRouter API key
  --output-dir PATH       Where to write outputs (default: .)
  --resume                Resume from last completed round

python ingest.py INPUT_DIR [--output OUTPUT_DIR]
```

---

## Convergence

The dialectic terminates when:
- >85% of claims are accepted by both agents
- Mean confidence gap across accepted claims < 0.15
- No new claims were introduced this round
- Change in accepted ratio from prior round < 0.02

If the loop runs without converging, the best partial results are synthesized anyway.

---

## Outputs

**consensus.md** — Three sections:
1. *Consensus Findings*: claims both agents accepted
2. *Unresolved Disputes*: claims still contested
3. *Retracted Claims*: claims that died under critique (equally valuable — knowing what's wrong is research)

**provenance.json** — Full chain of custody for every claim: who proposed it, who challenged it, how it changed.

**results.tsv** — Per-round metrics for analysis.

---

## Differences from karpathy/autoresearch

| autoresearch | autoresearch-rivals |
|---|---|
| 1 agent, 1 file (`train.py`) | 2 agents, each with own workspace |
| Metric: `val_bpb` (numeric) | Metric: structured claim registry + critique survival |
| Loop: edit → train → measure | Loop: research → produce → critique → revise → converge |
| Domain: ML training only | Domain: any research question |
| `program.md` drives one agent | `program_α.md` + `program_β.md` with rivalry protocol |
| No knowledge base | `corpus/` with RAG retrieval |
| Output: better `train.py` | Output: consensus document with provenance |
