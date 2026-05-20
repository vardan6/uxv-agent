# 0002. Two-Approval Model: Draft Approval ≠ Execution Approval

Date: 2026-05-10
Status: Accepted

## Context

The planning shell in `/ai` produces mission drafts through a LangGraph planning graph. The graph reaches an approval gate where the operator can approve or reject the draft.

Without a clear separation, "approval" could be read as both:

- "this draft is acceptable as a planning artifact"
- "publish these commands to the rover"

If approval at the planning gate were treated as execution authorization, an operator clicking Approve to acknowledge a reasonable plan could inadvertently authorize motion. The model could also be tempted, through prompt injection or honest mistake, to interpret "approved" as "execute now."

## Decision

Draft approval is a separate concept from execution approval, enforced at the service layer:

- `MissionDraftService` forces `execution_allowed: false` on every draft
- the planning graph only ever produces a draft; no node in the graph publishes commands
- a future command-staging and execution-approval design will be required to flip `execution_allowed` to `true` and to actually publish commands to the rover
- this future design is explicitly out of scope until it has its own ADR and safety review

## Consequences

- approving a draft is a low-stakes operator action
- `execution_allowed: false` is a structural invariant, not a runtime check
- the AI page can never directly cause rover motion regardless of model behavior, prompt content, or tool invocation
- adding execution requires real new design work; it is not a one-line config change
- the boundary is testable: any code path that flips `execution_allowed` to `true` is automatically suspect

## Alternatives Considered

- **Single approval step.** Rejected: too easy to misuse; conflates planning judgment with motion authorization.
- **Approval with severity levels.** Rejected: complexity without benefit when only one level (planning) actually exists today.
- **No approval gate, fully automatic execution after validation.** Rejected on safety grounds. Validation is necessary but not sufficient for execution authorization.

## Follow-Ups

- Command-staging design (Phase 7 in the AI plan) is its own future ADR
- Execution approval UX needs to be visually distinct from draft approval to prevent operator confusion
