"""Assemble the structured IncidentAnalysis from state.

V1 renders the report from evidence already in state, so every sentence is
traceable. V2 replaces the prose with an LLM call that receives *only* this
evidence and must return the same schema — the grounding contract stays.
"""

from __future__ import annotations

from app.agent.state import AgentState, RunStatus
from app.domain.models import EvidenceKind, IncidentAnalysis

#: Below this the agent says so instead of pretending to a conclusion.
CONFIDENCE_FLOOR = 0.6


async def build_analysis_node(state: AgentState) -> AgentState:
    service = state.get("target_service") or "unknown"
    evidence = list(state.get("evidence", []))
    hypotheses = list(state.get("hypotheses", []))
    context = state.get("context")

    symptoms = [e.summary for e in evidence if e.kind in (EvidenceKind.METRIC, EvidenceKind.ALERT)]
    log_symptoms = [e.summary for e in evidence if e.kind is EvidenceKind.LOG]

    best = max(hypotheses, key=lambda h: h.confidence, default=None)
    confidence = best.confidence if best else 0.0
    incident_start = next(
        (e.observed_at for e in evidence if e.source_tool == "detect_spike"), None
    )

    actions = _recommended_actions(context, best)
    analysis = IncidentAnalysis(
        service=service,
        incident_start=incident_start,
        symptoms=symptoms + log_symptoms,
        suspected_causes=sorted(hypotheses, key=lambda h: h.confidence, reverse=True),
        evidence=evidence,
        confidence=confidence,
        recommended_actions=actions,
        requires_human_review=True,
        summary=_summary(service, best, confidence),
    )

    return AgentState(
        current_step="generate_analysis",
        step_count=state.get("step_count", 0) + 1,
        analysis=analysis,
        status=RunStatus.RUNNING,
    )


def _recommended_actions(context, best) -> list[str]:
    if best is None or best.confidence < CONFIDENCE_FLOOR:
        return [
            "Widen the investigation window and re-run: the current evidence does not "
            "identify a cause with enough confidence to act on."
        ]
    actions = []
    if context and context.deployments:
        suspect = context.deployments[0]
        actions.append(f"Roll back {suspect.service} to the previous release and confirm recovery.")
    if context and context.commits:
        actions.append(
            f"Review {context.commits[0].short_sha} — {context.commits[0].message} — "
            "for the unhandled case visible in the logs."
        )
    actions.append("Add a regression test covering the failing code path before re-deploying.")
    return actions


def _summary(service: str, best, confidence: float) -> str:
    if best is None:
        return f"No conclusive cause found for the reported problem in {service}."
    qualifier = "likely" if confidence >= CONFIDENCE_FLOOR else "possible"
    return f"{qualifier.capitalize()} cause for the {service} incident: {best.statement}."
