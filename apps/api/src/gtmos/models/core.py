"""Tenancy and people who operate GTMOS."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from gtmos.models.base import Base, IdMixin, TimestampMixin


class Workspace(IdMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    seller_name: Mapped[str] = mapped_column(String(200))
    seller_product: Mapped[str] = mapped_column(Text)
    # "demo" workspaces are fully synthetic; the UI shows a persistent DEMO banner.
    mode: Mapped[str] = mapped_column(String(10), default="demo")
    # Seed data is generated relative to this instant so relative time windows stay meaningful.
    demo_anchor_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class User(IdMixin, TimestampMixin, Base):
    """A GTM team member who can own accounts (AE, SDR, AM) or operate the system (RevOps)."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("workspace_id", "email"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(40))  # ae | senior_ae | sdr | am | revops | admin
    team: Mapped[str | None] = mapped_column(String(80))  # e.g. "Enterprise West", "SDR Pool"
    territory: Mapped[str | None] = mapped_column(String(80))  # NA | EMEA | APAC | LATAM
    title: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(default=True)
    capacity: Mapped[int] = mapped_column(Integer, default=100)
