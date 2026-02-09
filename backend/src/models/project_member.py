from __future__ import annotations

from enum import Enum

from sqlalchemy import Enum as SqlEnum, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class ProjectMemberRole(str, Enum):
    owner = "owner"
    maintainer = "maintainer"
    contributor = "contributor"


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "agent_id", name="uq_project_members_unique"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id"), index=True, nullable=False
    )
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id"), index=True, nullable=False
    )
    role: Mapped[ProjectMemberRole] = mapped_column(
        SqlEnum(ProjectMemberRole, name="project_member_role"), nullable=False
    )
