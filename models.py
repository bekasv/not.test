from sqlalchemy import String, Integer, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from db import Base

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    attempts = relationship("Attempt", back_populates="user")

class Question(Base):
    __tablename__ = "questions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)   # question_id from JSON
    theme_id: Mapped[int] = mapped_column(Integer, index=True)
    theme_title: Mapped[str] = mapped_column(String(255))
    pick_count: Mapped[int] = mapped_column(Integer)             # internal quota
    qtype: Mapped[str] = mapped_column(String(32))               # single_choice/multiple_choice
    text: Mapped[str] = mapped_column(Text)
    opt0: Mapped[str] = mapped_column(Text)
    opt1: Mapped[str] = mapped_column(Text)
    opt2: Mapped[str] = mapped_column(Text)
    opt3: Mapped[str] = mapped_column(Text)
    correct_json: Mapped[str] = mapped_column(String(32))        # e.g. "[0,2]"

class Attempt(Base):
    __tablename__ = "attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    total_questions: Mapped[int] = mapped_column(Integer)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    score: Mapped[int] = mapped_column(Integer)
    percent: Mapped[float] = mapped_column(Integer)  # keep simple; can be Float if you want

    user = relationship("User", back_populates="attempts")
    details = relationship("AttemptDetail", back_populates="attempt", cascade="all, delete-orphan")

class AttemptDetail(Base):
    __tablename__ = "attempt_details"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id"), index=True)
    question_id: Mapped[int] = mapped_column(Integer, index=True)
    theme_id: Mapped[int] = mapped_column(Integer)
    qtype: Mapped[str] = mapped_column(String(32))
    selected_json: Mapped[str] = mapped_column(String(32))       # e.g. "[1]"
    correct_json: Mapped[str] = mapped_column(String(32))
    is_correct: Mapped[bool] = mapped_column(Boolean)

    attempt = relationship("Attempt", back_populates="details")
