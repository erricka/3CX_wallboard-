from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, Float, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


JsonType = JSON().with_variant(JSONB(), "postgresql")


class Agent(Base):
    __tablename__ = "agents"

    extension: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


class Queue(Base):
    __tablename__ = "queues"

    number: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    agent_extensions: Mapped[list] = mapped_column(JsonType, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


class AgentDailyStats(Base):
    __tablename__ = "agent_daily_stats"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    extension: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    inbound: Mapped[int] = mapped_column(Integer, default=0)
    outbound: Mapped[int] = mapped_column(Integer, default=0)
    missed: Mapped[int] = mapped_column(Integer, default=0)
    unanswered_slow: Mapped[int] = mapped_column(Integer, default=0)
    talk_seconds: Mapped[float] = mapped_column(Float, default=0)
    work_seconds: Mapped[float] = mapped_column(Float, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


class QueueDailyStats(Base):
    __tablename__ = "queue_daily_stats"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    queue: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    received: Mapped[int] = mapped_column(Integer, default=0)
    answered: Mapped[int] = mapped_column(Integer, default=0)
    missed: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


class CallRecord(Base):
    """One row of the 3CX call log (main rows and their segment sub-rows)."""

    __tablename__ = "call_records"
    __table_args__ = (Index("ix_call_records_day", "day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day: Mapped[date] = mapped_column(Date)
    call_id: Mapped[str] = mapped_column(String(64), default="")
    segment_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    indent: Mapped[int] = mapped_column(Integer, default=0)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_dn: Mapped[str] = mapped_column(String(64), default="")
    source_name: Mapped[str] = mapped_column(String(200), default="")
    destination_dn: Mapped[str] = mapped_column(String(64), default="")
    destination_name: Mapped[str] = mapped_column(String(200), default="")
    action_dn: Mapped[str] = mapped_column(String(64), default="")
    action_name: Mapped[str] = mapped_column(String(200), default="")
    answered: Mapped[bool] = mapped_column(Boolean, default=False)
    ringing_seconds: Mapped[float] = mapped_column(Float, default=0)
    talking_seconds: Mapped[float] = mapped_column(Float, default=0)
    reason: Mapped[str] = mapped_column(String(200), default="")
    raw: Mapped[dict] = mapped_column(JsonType, default=dict)


class AgentSession(Base):
    """Queue login session from the 3CX agent login history report."""

    __tablename__ = "agent_sessions"
    __table_args__ = (Index("ix_agent_sessions_day", "day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day: Mapped[date] = mapped_column(Date)
    extension: Mapped[str] = mapped_column(String(32))
    queue: Mapped[str] = mapped_column(String(32), default="")
    logged_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    logged_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentStatusLog(Base):
    """Status changes seen by the wallboard poller (Ready, Talking, Logoff, ...)."""

    __tablename__ = "agent_status_log"
    __table_args__ = (Index("ix_agent_status_log_ext_started", "extension", "started_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    extension: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SyncedDay(Base):
    __tablename__ = "synced_days"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # True once the day is over and every source synced cleanly; it is not fetched again.
    complete: Mapped[bool] = mapped_column(Boolean, default=False)
