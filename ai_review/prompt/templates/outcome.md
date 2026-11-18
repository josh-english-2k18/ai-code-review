## Write the review

Return a concise Markdown report with the strongest challenges first. Under **Challenges**, give each challenge a heading that names the specific behavioral contradiction. Use short paragraphs for the following.

- **Impact.** What can go wrong, for whom, and under what conditions.
- **Evidence status.** Mark the behavior **Reproduced** or **Code-traced**. Use **Not yet established** for a material question that lacks behavioral evidence.
- **Behavioral claim.** State the reachable conditions, execution path, and observed or inferred result. Cite the code and checks that establish it.
- **Intent basis.** Cite the applicable guarantee and say whether it is explicit or inferred. Identify any evidence that conflicts with it.
- **Adversarial examination.** Summarize what you checked to disprove either claim and what you learned.
- **Verification.** Give the author the smallest realistic scenario to test both claims, with expected observations and commands where appropriate.
- **Disproof conditions.** Name the result or authoritative evidence that would invalidate the challenge.
- **Preservation constraints.** Identify existing capabilities, invariants, or deliberate behaviors an eventual correction must preserve.

Leave the design response to the author.

The Home navigation example illustrates the reasoning that makes a challenge testable.

```markdown
## Challenges

### The redesign may have broken established answer navigation

**Behavioral claim.** Given an answer containing a valid project-creation action, Home fails to render the corresponding navigation control.

**Intent basis.** PR #527 introduced next-step actions. The redesign explicitly claimed to preserve that functionality.

**Verification.** Construct an answer containing the real API target shape. Run the scenario against the new implementation and the previous behavior. Establish whether the action is missing and whether its removal was intentional.

**Disproof conditions.** The action renders through another supported path, or authoritative product context establishes that the behavior was intentionally superseded.

**Requested change.** None.
```

## Disposition

Use **Challenges** for defensible contradictions. Put consequential ambiguities under **Unresolved questions**, with the evidence or decision that would resolve them.

Use **No material challenges established** after an investigation that yields no candidates meeting the standard. Use **Review blocked** when missing access or evidence prevents meaningful investigation. Close with a brief **Scope** note on what you inspected, the validation you performed, and any limit that affects confidence.
