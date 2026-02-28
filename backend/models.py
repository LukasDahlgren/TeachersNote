from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Lecture(Base):
    __tablename__ = "lectures"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    name       = Column(String(255), nullable=False)
    is_demo    = Column(Boolean, nullable=False, default=False)
    is_archived = Column(Boolean, nullable=False, default=False)
    pptx_path  = Column(String(512), nullable=True)
    pdf_path   = Column(String(512), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    slides              = relationship("Slide", back_populates="lecture", cascade="all, delete-orphan")
    transcript_segments = relationship("TranscriptSegment", back_populates="lecture", cascade="all, delete-orphan")
    alignments          = relationship("Alignment", back_populates="lecture", cascade="all, delete-orphan")
    enriched_slides     = relationship("EnrichedSlide", back_populates="lecture", cascade="all, delete-orphan")


class Slide(Base):
    __tablename__ = "slides"
    __table_args__ = (UniqueConstraint("lecture_id", "slide_number"),)

    id           = Column(Integer, primary_key=True, autoincrement=True)
    lecture_id   = Column(Integer, ForeignKey("lectures.id", ondelete="CASCADE"), nullable=False)
    slide_number = Column(SmallInteger, nullable=False)
    text         = Column(Text, nullable=False)

    lecture = relationship("Lecture", back_populates="slides")


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (UniqueConstraint("lecture_id", "segment_index"),)

    id            = Column(Integer, primary_key=True, autoincrement=True)
    lecture_id    = Column(Integer, ForeignKey("lectures.id", ondelete="CASCADE"), nullable=False)
    segment_index = Column(SmallInteger, nullable=False)
    start_time    = Column(Float, nullable=False)
    end_time      = Column(Float, nullable=False)
    text          = Column(Text, nullable=False)

    lecture = relationship("Lecture", back_populates="transcript_segments")


class Alignment(Base):
    __tablename__ = "alignments"
    __table_args__ = (UniqueConstraint("lecture_id", "slide_number"),)

    id            = Column(Integer, primary_key=True, autoincrement=True)
    lecture_id    = Column(Integer, ForeignKey("lectures.id", ondelete="CASCADE"), nullable=False)
    slide_number  = Column(SmallInteger, nullable=False)
    start_segment = Column(SmallInteger, nullable=False)
    end_segment   = Column(SmallInteger, nullable=False)

    lecture = relationship("Lecture", back_populates="alignments")


class EnrichedSlide(Base):
    __tablename__ = "enriched_slides"
    __table_args__ = (UniqueConstraint("lecture_id", "slide_number"),)

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    lecture_id         = Column(Integer, ForeignKey("lectures.id", ondelete="CASCADE"), nullable=False)
    slide_number       = Column(SmallInteger, nullable=False)
    summary            = Column(Text, nullable=False)
    slide_content      = Column(Text, nullable=False)
    lecturer_additions = Column(Text, nullable=False)
    key_takeaways      = Column(JSON, nullable=False)

    lecture = relationship("Lecture", back_populates="enriched_slides")
