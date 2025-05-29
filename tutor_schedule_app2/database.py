import config
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Boolean, UniqueConstraint, Float
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime

Base = declarative_base()

class Student(Base):
    __tablename__ = 'students'
    id = Column(Integer, primary_key=True)
    full_name = Column(String, nullable=False)
    lessons_count = Column(Integer, default=0) # Total lessons count, not remaining
    telegram_id = Column(String, unique=True, nullable=True) # Can be null if no Telegram
    receive_notifications = Column(Boolean, default=True) # New field for notifications
    is_archived = Column(Boolean, default=False)  # Новое поле для архивации
    lessons = relationship('Lesson', backref='student', lazy=True, cascade="all, delete-orphan")
    parents = relationship('Parent', backref='student', lazy=True, cascade="all, delete-orphan")
    homeworks = relationship('Homework', backref='student', lazy=True, cascade="all, delete-orphan")
    payments = relationship('Payment', backref='student', lazy=True, cascade="all, delete-orphan") # New relationship

class Lesson(Base):
    __tablename__ = 'lessons'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('students.id'))
    date_time = Column(DateTime, nullable=False)
    status = Column(String, default='scheduled') # scheduled, completed, cancelled, no_show
    report_status = Column(String, default='pending') # pending, completed, cancelled, no_show
    topic_covered = Column(String, nullable=True)
    video_link = Column(String, nullable=True)
    next_lesson_date = Column(DateTime, nullable=True)
    homework = relationship('Homework', backref='lesson', uselist=False, cascade="all, delete-orphan")


class Tutor(Base):
    __tablename__ = 'tutor'
    id = Column(Integer, primary_key=True)
    chat_id = Column(String, unique=True, nullable=False)

class Parent(Base):
    __tablename__ = 'parents'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('students.id'), nullable=False)
    telegram_id = Column(String, nullable=False) # Telegram ID of the parent
    __table_args__ = (
        UniqueConstraint('student_id', 'telegram_id', name='_student_parent_uc'),
    )

class Homework(Base):
    __tablename__ = 'homeworks'
    id = Column(Integer, primary_key=True)
    lesson_id = Column(Integer, ForeignKey('lessons.id'), nullable=True) # Can be tied to a specific lesson
    student_id = Column(Integer, ForeignKey('students.id'), nullable=False)
    description = Column(String, nullable=False)
    due_date = Column(DateTime, nullable=True) # Optional due date
    is_completed = Column(Boolean, default=False)
    completed_date = Column(DateTime, nullable=True)
    telegram_message_id = Column(String, nullable=True) # To edit the message after completion

class Payment(Base): # New table for payments
    __tablename__ = 'payments'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('students.id'), nullable=False)
    amount = Column(Float, nullable=False)
    payment_date = Column(DateTime, default=datetime.now)
    description = Column(String, nullable=True)

engine = create_engine(f'sqlite:///{config.DB_NAME}')
Base.metadata.create_all(engine)

Session = sessionmaker(bind=engine)