from __future__ import annotations

from datetime import datetime

from src.models.proposal import ProposalStatus


def compute_vote_result(
    yes: int,
    no: int,
    quorum_min: int,
    approval_bps: int,
) -> tuple[str, str]:
    total_votes = yes + no
    if total_votes < quorum_min:
        return "rejected", "quorum_not_met"
    if total_votes <= 0:
        return "rejected", "no_votes"

    yes_bps = (yes * 10000) // total_votes
    if yes_bps >= approval_bps:
        return "approved", "approval_threshold_met"
    return "rejected", "approval_threshold_not_met"


def can_finalize(now: datetime, voting_ends_at: datetime | None, status: ProposalStatus) -> bool:
    if status != ProposalStatus.voting:
        return False
    if voting_ends_at is None:
        return False
    return now >= voting_ends_at


def next_status(current: ProposalStatus, action: str) -> ProposalStatus:
    transitions: dict[tuple[ProposalStatus, str], ProposalStatus] = {
        (ProposalStatus.draft, "submit_to_discussion"): ProposalStatus.discussion,
        (ProposalStatus.draft, "submit_to_voting"): ProposalStatus.voting,
        (ProposalStatus.discussion, "start_voting"): ProposalStatus.voting,
        (ProposalStatus.voting, "finalize_approved"): ProposalStatus.approved,
        (ProposalStatus.voting, "finalize_rejected"): ProposalStatus.rejected,
    }
    key = (current, action)
    if key not in transitions:
        raise ValueError(f"Invalid proposal transition: {current} via {action}")
    return transitions[key]
