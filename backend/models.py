from datetime import datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, JSON, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Lecture(Base):
    __tablename__ = "lectures"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String(255), nullable=False)
    is_demo     = Column(Boolean, nullable=False, default=False)
    is_archived = Column(Boolean, nullable=False, default=False)
    is_deleted  = Column(Boolean, nullable=False, default=False)
    is_approved = Column(Boolean, nullable=False, default=False)
    course_id   = Column(String(64), nullable=True, index=True)
    uploaded_by = Column(String(255), nullable=True)
    pptx_path   = Column(String(512), nullable=True)
    pdf_path    = Column(String(512), nullable=True)
    created_at  = Column(DateTime, nullable=False, default=datetime.utcnow)

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


class LectureSave(Base):
    __tablename__ = "lecture_saves"
    __table_args__ = (UniqueConstraint("user_id", "lecture_id"),)

    id         = Column(Integer, primary_key=True, autoincrement=True)
    user_id    = Column(String(255), nullable=False, index=True)
    lecture_id = Column(Integer, ForeignKey("lectures.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AdminUser(Base):
    __tablename__ = "admin_users"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    user_id       = Column(String(255), nullable=False, unique=True, index=True)
    registered_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Program(Base):
    __tablename__ = "programs"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    code       = Column(String(64), nullable=False, unique=True, index=True)
    name       = Column(String(255), nullable=False)
    is_active  = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    courses  = relationship("Course", secondary="program_courses", back_populates="programs")
    profiles = relationship("StudentProfile", back_populates="program")
    course_plan_rows = relationship("ProgramCoursePlan", back_populates="program", cascade="all, delete-orphan")


class Course(Base):
    __tablename__ = "courses"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    code       = Column(String(64), nullable=False, unique=True, index=True)
    display_code = Column(String(64), nullable=True)
    name       = Column(String(255), nullable=False)
    is_active  = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    programs = relationship("Program", secondary="program_courses", back_populates="courses")
    students = relationship("StudentProfile", secondary="student_courses", back_populates="selected_courses")
    plan_rows = relationship("ProgramCoursePlan", back_populates="course")


class ProgramCourse(Base):
    __tablename__ = "program_courses"

    program_id = Column(Integer, ForeignKey("programs.id", ondelete="CASCADE"), primary_key=True)
    course_id  = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ProgramCoursePlan(Base):
    __tablename__ = "program_course_plan"
    __table_args__ = (
        UniqueConstraint("program_id", "snapshot_date", "display_order"),
    )

    id            = Column(Integer, primary_key=True, autoincrement=True)
    program_id    = Column(Integer, ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id     = Column(Integer, ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True)
    term_label    = Column(String(128), nullable=False)
    group_type    = Column(String(16), nullable=False)
    group_label   = Column(String(255), nullable=True)
    course_code   = Column(String(64), nullable=True)
    course_name_sv = Column(String(255), nullable=False)
    course_url    = Column(Text, nullable=False)
    display_order = Column(Integer, nullable=False)
    snapshot_date = Column(Date, nullable=False)
    created_at    = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at    = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    program = relationship("Program", back_populates="course_plan_rows")
    course = relationship("Course", back_populates="plan_rows")


class StudentProfile(Base):
    __tablename__ = "student_profiles"

    user_id    = Column(String(255), primary_key=True)
    program_id = Column(Integer, ForeignKey("programs.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    program          = relationship("Program", back_populates="profiles")
    selected_courses = relationship("Course", secondary="student_courses", back_populates="students")


class StudentCourse(Base):
    __tablename__ = "student_courses"

    user_id    = Column(String(255), ForeignKey("student_profiles.user_id", ondelete="CASCADE"), primary_key=True)
    course_id  = Column(Integer, ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
