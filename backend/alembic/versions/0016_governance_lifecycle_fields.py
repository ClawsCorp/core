"""governance lifecycle fields and vote semantics

Revision ID: 0016_governance_lifecycle_fields
Revises: 0015_reputation_events_v1
Create Date: 2026-02-12 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0016_governance_lifecycle_fields"
down_revision = "0015_reputation_events_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE proposal_status ADD VALUE IF NOT EXISTS 'discussion'")

    op.add_column("proposals", sa.Column("discussion_ends_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("proposals", sa.Column("voting_starts_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("proposals", sa.Column("voting_ends_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("proposals", sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("proposals", sa.Column("finalized_outcome", sa.String(length=16), nullable=True))
    op.add_column("proposals", sa.Column("yes_votes_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("proposals", sa.Column("no_votes_count", sa.Integer(), nullable=False, server_default="0"))

    op.add_column("votes", sa.Column("value", sa.Integer(), nullable=True))
    op.add_column(
        "votes",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.execute("UPDATE votes SET value = CASE WHEN vote = 'approve' THEN 1 ELSE -1 END")

    op.execute(
        """
        UPDATE proposals AS p
        SET
            yes_votes_count = COALESCE(v.yes_count, 0),
            no_votes_count = COALESCE(v.no_count, 0)
        FROM (
            SELECT
                p2.id AS proposal_pk,
                COUNT(vt.id) FILTER (WHERE vt.value = 1) AS yes_count,
                COUNT(vt.id) FILTER (WHERE vt.value = -1) AS no_count
            FROM proposals AS p2
            LEFT JOIN votes AS vt ON vt.proposal_id = p2.id
            GROUP BY p2.id
        ) AS v
        WHERE p.id = v.proposal_pk
        """
    )

    op.alter_column("votes", "value", nullable=False)
    op.drop_column("votes", "vote")
    op.drop_column("votes", "reputation_stake")
    op.drop_column("votes", "comment")

    op.create_check_constraint("ck_votes_value_valid", "votes", "value IN (-1, 1)")


def downgrade() -> None:
    op.drop_constraint("ck_votes_value_valid", "votes", type_="check")

    op.add_column("votes", sa.Column("comment", sa.Text(), nullable=True))
    op.add_column("votes", sa.Column("reputation_stake", sa.Integer(), nullable=False, server_default="1"))
    vote_choice_enum = sa.Enum("approve", "reject", name="vote_choice")
    vote_choice_enum.create(op.get_bind(), checkfirst=True)
    op.add_column("votes", sa.Column("vote", vote_choice_enum, nullable=False, server_default="approve"))
    op.execute("UPDATE votes SET vote = CASE WHEN value = 1 THEN 'approve'::vote_choice ELSE 'reject'::vote_choice END")

    op.drop_column("votes", "updated_at")
    op.drop_column("votes", "value")

    op.drop_column("proposals", "no_votes_count")
    op.drop_column("proposals", "yes_votes_count")
    op.drop_column("proposals", "finalized_outcome")
    op.drop_column("proposals", "finalized_at")
    op.drop_column("proposals", "voting_ends_at")
    op.drop_column("proposals", "voting_starts_at")
    op.drop_column("proposals", "discussion_ends_at")
