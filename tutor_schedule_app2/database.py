import config
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, Boolean, UniqueConstraint, Float
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
    can_create_courses = Column(Boolean, default=False)  # Разрешение на создание курсов
    created_at = Column(DateTime, default=datetime.now)
    reset_token = Column(String, nullable=True)
    reset_token_expires = Column(DateTime, nullable=True)
    bot_token = Column(String, nullable=True)  # Токен бота для уведомлений
    
    # Связь со студентом (если роль student)
    student_id = Column(Integer, ForeignKey('students.id'), nullable=True)
    student = relationship('Student', foreign_keys=[student_id], backref='user_account', uselist=False)
    
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
    
    # Связь с репетитором
    tutor_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    tutor = relationship('User', foreign_keys=[tutor_id], backref='students')
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

# ==================== МОДЕЛИ ДЛЯ СИСТЕМЫ КУРСОВ ====================

class Course(Base):
    __tablename__ = 'courses'
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    tutor_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Связи
    tutor = relationship('User', foreign_keys=[tutor_id])
    modules = relationship('CourseModule', back_populates='course', cascade='all, delete-orphan')
    enrollments = relationship('CourseEnrollment', back_populates='course', cascade='all, delete-orphan')

class CourseModule(Base):
    __tablename__ = 'course_modules'
    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey('courses.id'), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    order_index = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    
    # Связи
    course = relationship('Course', back_populates='modules')
    lessons = relationship('CourseLesson', back_populates='module', cascade='all, delete-orphan')

class CourseLesson(Base):
    __tablename__ = 'course_lessons'
    id = Column(Integer, primary_key=True)
    module_id = Column(Integer, ForeignKey('course_modules.id'), nullable=False)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=True)  # HTML контент урока
    order_index = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    
    # Связи
    module = relationship('CourseModule', back_populates='lessons')
    materials = relationship('CourseMaterial', back_populates='lesson', cascade='all, delete-orphan')
    assignments = relationship('CourseAssignment', back_populates='lesson', cascade='all, delete-orphan')
    blocks = relationship('LessonBlock', back_populates='lesson', cascade='all, delete-orphan', order_by='LessonBlock.order_index')

class CourseMaterial(Base):
    __tablename__ = 'course_materials'
    id = Column(Integer, primary_key=True)
    lesson_id = Column(Integer, ForeignKey('course_lessons.id'), nullable=False)
    title = Column(String, nullable=False)
    material_type = Column(String, nullable=False)  # 'image', 'video', 'document', 'presentation'
    file_path = Column(String, nullable=False)  # Путь к файлу
    file_size = Column(Integer, nullable=True)  # Размер в байтах
    original_filename = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    
    # Связи
    lesson = relationship('CourseLesson', back_populates='materials')

class LessonBlock(Base):
    __tablename__ = 'lesson_blocks'
    id = Column(Integer, primary_key=True)
    lesson_id = Column(Integer, ForeignKey('course_lessons.id'), nullable=False)
    block_type = Column(String, nullable=False)  # 'text', 'material'
    title = Column(String, nullable=True)  # Заголовок блока (опционально)
    content = Column(Text, nullable=True)  # Текстовое содержимое для блоков типа 'text'
    material_id = Column(Integer, ForeignKey('course_materials.id'), nullable=True)  # Ссылка на материал для блоков типа 'material'
    order_index = Column(Integer, default=0)  # Порядок блока в уроке
    created_at = Column(DateTime, default=datetime.now)
    
    # Связи
    lesson = relationship('CourseLesson', back_populates='blocks')
    material = relationship('CourseMaterial')

class CourseAssignment(Base):
    __tablename__ = 'course_assignments'
    id = Column(Integer, primary_key=True)
    lesson_id = Column(Integer, ForeignKey('course_lessons.id'), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    assignment_type = Column(String, default='text')  # 'text', 'file', 'quiz'
    is_required = Column(Boolean, default=True)
    max_points = Column(Integer, default=100)
    created_at = Column(DateTime, default=datetime.now)
    
    # Связи
    lesson = relationship('CourseLesson', back_populates='assignments')
    submissions = relationship('CourseSubmission', back_populates='assignment', cascade='all, delete-orphan')

class CourseEnrollment(Base):
    __tablename__ = 'course_enrollments'
    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey('courses.id'), nullable=False)
    student_id = Column(Integer, ForeignKey('students.id'), nullable=False)
    enrolled_at = Column(DateTime, default=datetime.now)
    is_active = Column(Boolean, default=True)
    progress_percentage = Column(Float, default=0.0)  # Процент прохождения курса
    current_lesson_id = Column(Integer, ForeignKey('course_lessons.id'), nullable=True)  # Текущий доступный урок
    completed_lessons = Column(Text, default='')  # JSON список ID завершенных уроков
    
    # Связи
    course = relationship('Course', back_populates='enrollments')
    student = relationship('Student')
    current_lesson = relationship('CourseLesson', foreign_keys=[current_lesson_id])
    submissions = relationship('CourseSubmission', back_populates='enrollment', cascade='all, delete-orphan')
    
    def get_completed_lesson_ids(self):
        """Возвращает список ID завершенных уроков"""
        if not self.completed_lessons:
            return []
        try:
            import json
            return json.loads(self.completed_lessons)
        except:
            return []
    
    def mark_lesson_completed(self, lesson_id):
        """Отмечает урок как завершенный и открывает следующий"""
        import json
        from sqlalchemy.orm import object_session
        
        completed_ids = self.get_completed_lesson_ids()
        if lesson_id not in completed_ids:
            completed_ids.append(lesson_id)
            self.completed_lessons = json.dumps(completed_ids)
            
            # Находим следующий урок
            session = object_session(self)
            if session:
                next_lesson = self._get_next_lesson(session, lesson_id)
                if next_lesson:
                    self.current_lesson_id = next_lesson.id
                
                # Обновляем процент прохождения
                self._update_progress_percentage(session)
    
    def _get_next_lesson(self, session, current_lesson_id):
        """Находит следующий урок в курсе"""
        # Получаем текущий урок
        current_lesson = session.get(CourseLesson, current_lesson_id)
        if not current_lesson:
            return None
        
        # Ищем следующий урок в том же модуле
        next_lesson = session.query(CourseLesson)\
            .filter(CourseLesson.module_id == current_lesson.module_id)\
            .filter(CourseLesson.order_index > current_lesson.order_index)\
            .order_by(CourseLesson.order_index)\
            .first()
        
        if next_lesson:
            return next_lesson
        
        # Если в модуле больше нет уроков, ищем первый урок следующего модуля
        next_module = session.query(CourseModule)\
            .filter(CourseModule.course_id == self.course_id)\
            .filter(CourseModule.order_index > current_lesson.module.order_index)\
            .order_by(CourseModule.order_index)\
            .first()
        
        if next_module:
            return session.query(CourseLesson)\
                .filter(CourseLesson.module_id == next_module.id)\
                .order_by(CourseLesson.order_index)\
                .first()
        
        return None  # Курс завершен
    
    def _update_progress_percentage(self, session):
        """Обновляет процент прохождения курса"""
        # Считаем общее количество уроков в курсе
        total_lessons = session.query(CourseLesson)\
            .join(CourseModule)\
            .filter(CourseModule.course_id == self.course_id)\
            .count()
        
        if total_lessons > 0:
            completed_count = len(self.get_completed_lesson_ids())
            self.progress_percentage = (completed_count / total_lessons) * 100
        else:
            self.progress_percentage = 0.0
    
    def can_access_lesson(self, lesson_id):
        """Проверяет, может ли студент получить доступ к уроку"""
        # Студент может получить доступ к уроку, если:
        # 1. Это текущий урок
        # 2. Это уже завершенный урок
        
        if lesson_id == self.current_lesson_id:
            return True
        
        completed_ids = self.get_completed_lesson_ids()
        return lesson_id in completed_ids

class CourseSubmission(Base):
    __tablename__ = 'course_submissions'
    id = Column(Integer, primary_key=True)
    assignment_id = Column(Integer, ForeignKey('course_assignments.id'), nullable=False)
    enrollment_id = Column(Integer, ForeignKey('course_enrollments.id'), nullable=False)
    content = Column(Text, nullable=True)  # Текстовый ответ
    file_path = Column(String, nullable=True)  # Путь к файлу ответа
    submitted_at = Column(DateTime, default=datetime.now)
    is_checked = Column(Boolean, default=False)
    status = Column(String, default='submitted')  # submitted, approved, rejected
    points = Column(Integer, nullable=True)  # Полученные баллы
    tutor_feedback = Column(Text, nullable=True)  # Комментарий репетитора
    checked_at = Column(DateTime, nullable=True)
    
    # Связи
    assignment = relationship('CourseAssignment', back_populates='submissions')
    enrollment = relationship('CourseEnrollment', back_populates='submissions')
    
    def is_approved(self):
        """Проверяет, одобрено ли задание"""
        return self.status == 'approved'
    
    def is_rejected(self):
        """Проверяет, отклонено ли задание"""
        return self.status == 'rejected'

engine = create_engine(
    f'sqlite:///{config.DB_NAME}',
    connect_args={'timeout': 30, 'check_same_thread': False},
    pool_pre_ping=True
)
Base.metadata.create_all(engine)

Session = sessionmaker(bind=engine)