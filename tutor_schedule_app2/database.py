import config
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Boolean, UniqueConstraint, Float
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime, timedelta
import hashlib
import secrets

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # 'admin', 'tutor', 'student'
    is_active = Column(Boolean, default=True)
    is_approved = Column(Boolean, default=False)  # Для репетиторов - требует одобрения админа
    created_at = Column(DateTime, default=datetime.now)
    reset_token = Column(String, nullable=True)
    reset_token_expires = Column(DateTime, nullable=True)
    bot_token = Column(String, nullable=True)  # Токен бота для уведомлений
    
    # Связь со студентом (если роль student)
    student_id = Column(Integer, ForeignKey('students.id'), nullable=True)
    student = relationship('Student', backref='user_account', uselist=False)
    
    def set_password(self, password):
        """Хеширование пароля"""
        self.password_hash = hashlib.sha256(password.encode()).hexdigest()
    
    def check_password(self, password):
        """Проверка пароля"""
        return self.password_hash == hashlib.sha256(password.encode()).hexdigest()
    
    def generate_reset_token(self):
        """Генерация токена для сброса пароля"""
        self.reset_token = secrets.token_urlsafe(32)
        self.reset_token_expires = datetime.now() + timedelta(hours=1)
        return self.reset_token

class Invitation(Base):
    __tablename__ = 'invitations'
    id = Column(Integer, primary_key=True)
    token = Column(String, unique=True, nullable=False)
    email = Column(String, nullable=False)
    role = Column(String, nullable=False)  # 'tutor', 'student'
    student_id = Column(Integer, ForeignKey('students.id'), nullable=True)  # Для студентов
    created_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    expires_at = Column(DateTime, nullable=False)
    is_used = Column(Boolean, default=False)
    
    # Связи
    student = relationship('Student', backref='invitations')
    creator = relationship('User', backref='created_invitations')
    
    def is_expired(self):
        return datetime.now() > self.expires_at
    
    def generate_token(self):
        self.token = secrets.token_urlsafe(32)
        return self.token

class Student(Base):
    __tablename__ = 'students'
    id = Column(Integer, primary_key=True)
    full_name = Column(String, nullable=False)
    lessons_count = Column(Integer, default=0) # Total lessons count, not remaining
    telegram_chat_id = Column(String, unique=True, nullable=True) # Числовой chat_id из Telegram (msg.chat.id)
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
    status = Column(String, default='запланирован') # запланирован, проведен, отменен, не_пришел
    report_status = Column(String, default='ожидает') # ожидает, проведен, отменен, не_пришел
    topic_covered = Column(String, nullable=True)
    video_link = Column(String, nullable=True)
    video_status = Column(String, default='pending') # pending, added, later
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
    telegram_chat_id = Column(String, nullable=False) # Числовой chat_id родителя из Telegram (msg.chat.id)
    __table_args__ = (
        UniqueConstraint('student_id', 'telegram_chat_id', name='_student_parent_uc'),
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
    student_comment = Column(String, nullable=True) # Комментарий студента к ДЗ
    is_confirmed_by_tutor = Column(Boolean, default=False) # Подтверждение репетитором
    submitted_date = Column(DateTime, nullable=True) # Дата отправки студентом

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