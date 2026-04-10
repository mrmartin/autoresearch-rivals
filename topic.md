# Research Question

Is the statement "NP ≠ P" formally unprovable (independent) within standard mathematical systems such as Peano Arithmetic (PA) or ZFC? Construct the strongest possible formal argument — either a proof of independence, or a precise identification of what is missing for such a proof.

## Clarification

"NP is undecidable" in the sense of formal undecidability (Gödel incompleteness): the question is whether the assertion P ≠ NP (or P = NP) cannot be proved or disproved within standard foundational systems. This is distinct from asking whether NP-complete problems are computationally decidable (they are — just not in polynomial time).

The research program asks: **is the P vs NP question in the same category as the Continuum Hypothesis — a formally independent statement that can neither be proved nor refuted from the ZFC axioms?**

## Key Frameworks to Engage

### Proof Complexity Route
- Cook-Reckhow framework: proof systems as polynomial-time computable functions P(x, y)
- Krajíček-Pudlák 1989 correspondence: superpolynomial lower bounds for all proof systems ↔ NP ⊄ coNP/poly
- If no proof system has polynomial-size proofs for all tautologies, then NP ≠ coNP (a consequence of P ≠ NP)
- Ben-David & Halevi 1992: constructed a model of PA where P = NP holds, suggesting formal independence

### Bounded Arithmetic Route
- Wilkie-Paris 1987: PA does not prove the totality of superexponential functions
- Theories S²₂, T²₂ (Buss 1986): relate to polynomial-time and NP respectively
- If P ≠ NP is provable in PA, it must be provable in a bounded fragment — what fragment?

### Natural Proofs Barrier (Razborov-Rudich 1994)
- Any "natural" proof technique for circuit lower bounds can be turned into a pseudorandom function generator
- Under standard cryptographic assumptions, natural proofs cannot prove NP ⊄ P/poly
- This is a barrier about proof *methods*, not formal provability, but connects to the meta-question

### Relativization Barrier (Baker-Gill-Solovay 1975)
- There exist oracles A, B such that Pᴬ = NPᴬ and Pᴮ ≠ NPᴮ
- Any proof of P vs NP must be non-relativizing
- Ben-David & Halevi use this: the existence of oracle models is evidence of formal independence

### Algebraization Barrier (Aaronson-Wigderson 2009)
- Extends relativization: algebraic oracle separations also block standard techniques
- Establishes that both P = NP and P ≠ NP are consistent with all algebraic extensions

## Success Criteria

A successful research output achieves ONE of:

1. **Independence proof sketch**: Show (or cite) that there is a model of PA (or ZFC) in which P = NP holds, and argue that there is a model in which P ≠ NP holds — establishing formal independence.

2. **Gap analysis**: Precisely identify what theorem, if proved, would close the gap toward independence — what is the single missing piece?

3. **Barrier synthesis**: Formally connect all three barriers (relativization, natural proofs, algebraization) to show they collectively constitute evidence for formal independence, not just computational difficulty.

## Constraints on All Claims

- Every claim must cite a specific theorem, author, and year
- Claims must distinguish oracle-relative from non-relativizing results
- Confidence levels must be calibrated: do not claim HIGH confidence for open questions
- The agents have access to:
  - *Proof Complexity* (Krajíček, Cambridge Encyclopedia series)
  - *Modern Mathematical Logic* (Weiss/D'Mello or similar)
  - *From Frege to Gödel: A Source Book in Mathematical Logic, 1879–1931* (van Heijenoort)
