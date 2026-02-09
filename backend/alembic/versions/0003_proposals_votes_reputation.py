"""add proposals votes reputation ledger

Revision ID: 0003_proposals_votes_reputation
Revises: 0002_agents_audit_logs
Create Date: 2024-01-03 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_proposals_votes_reputation"
down_revision = "0002_agents_audit_logs"
branch_labels = None
depends_on = None

proposal_status_enum = sa.Enum(
    "draft", "voting", "approved", "rejected", name="proposal_status"
)
vote_choice_enum = sa.Enum("approve", "reject", name="vote_choice")


def upgrade() -> None:
    op.create_table(
        "proposals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("proposal_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description_md", sa.Text(), nullable=False),
        sa.Column("status", proposal_status_enum, nullable=False),
        sa.Column("author_agent_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["author_agent_id"], ["agents.id"]),
    )
    op.create_index("ix_proposals_proposal_id", "proposals", ["proposal_id"], unique=True)
    op.create_index("ix_proposals_author_agent_id", "proposals", ["author_agent_id"])

    op.create_table(
        "votes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("proposal_id", sa.Integer(), nullable=False),
        sa.Column("voter_agent_id", sa.Integer(), nullable=False),
        sa.Column("vote", vote_choice_enum, nullable=False),
        sa.Column("reputation_stake", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"]),
        sa.ForeignKeyConstraint(["voter_agent_id"], ["agents.id"]),
        sa.UniqueConstraint("proposal_id", "voter_agent_id", name="uq_votes_unique"),
    )
    op.create_index("ix_votes_proposal_id", "votes", ["proposal_id"])
    op.create_index("ix_votes_voter_agent_id", "votes", ["voter_agent_id"])

    op.create_table(
        "reputation_ledger",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("ref_type", sa.String(length=32), nullable=False),
        sa.Column("ref_id", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
    )
    op.create_index("ix_reputation_ledger_agent_id", "reputation_ledger", ["agent_id"])
    op.create_index(
        "ix_reputation_ledger_created_at",
        "reputation_ledger",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_reputation_ledger_created_at", table_name="reputation_ledger")
    op.drop_index("ix_reputation_ledger_agent_id", table_name="reputation_ledger")
    op.drop_table("reputation_ledger")

    op.drop_index("ix_votes_voter_agent_id", table_name="votes")
    op.drop_index("ix_votes_proposal_id", table_name="votes")
    op.drop_table("votes")

    op.drop_index("ix_proposals_author_agent_id", table_name="proposals")
    op.drop_index("ix_proposals_proposal_id", table_name="proposals")
    op.drop_table("proposals")

    bind = op.get_bind()
    vote_choice_enum.drop(bind, checkfirst=True)
    proposal_status_enum.drop(bind, checkfirst=True)
