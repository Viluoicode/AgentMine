"""Normalized business facts plus participant context, never an asserted outcome."""

from dataclasses import dataclass

from agentmine.domain.eligibility import EligibilityFacts, ParticipantProfile


@dataclass(frozen=True, slots=True)
class EligibilityCheckRequest:
    facts: EligibilityFacts
    profile: ParticipantProfile
