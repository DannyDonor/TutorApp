from flask import Flask, render_template, request, redirect, session as flask_session, url_for, flash
from database import (Session, Student, Lesson, Tutor, Parent, Homework, Payment, User, Invitation,
                     Course, CourseModule, CourseLesson, CourseMaterial, CourseAssignment, 
                     CourseEnrollment, CourseSubmission, LessonBlock)
import config
import os
from datetime import datetime, timedelta, time
from contextlib import contextmanager
from sqlalchemy.exc import SQLAlchemyError, AmbiguousForeignKeysError, OperationalError
from sqlalchemy import or_ # Для поиска
from sqlalchemy import func
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps

app = Flask(__name__)
app.secret_key = 'secret_key'

# Функция для отправки email
def send_email(to_email, subject, body):
    """Отправка email для восстановления пароля"""
    try:
        # Настройки SMTP (замените на ваши)
        smtp_server = "smtp.gmail.com"
        smtp_port = 587
        sender_email = "your_email@gmail.com"  # Замените на ваш email
        sender_password = "your_password"  # Замените на ваш пароль
        
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = to_email
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        text = msg.as_string()
        server.sendmail(sender_email, to_email, text)
        server.quit()
        return True
    except Exception as e:
        print(f"Ошибка отправки email: {e}")
        return False

# Декоратор для проверки ролей
def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in flask_session:
                return redirect(url_for('login'))
            
            user_role = flask_session.get('role')
            if user_role not in roles:
                flash('У вас нет прав для доступа к этой странице', 'error')
                # Перенаправляем на соответствующую роли страницу
                if user_role == 'student':
                    return redirect(url_for('student_dashboard'))
                elif user_role in ['admin', 'tutor']:
                    return redirect(url_for('today_lessons'))
                else:
                    return redirect(url_for('login'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def get_current_user_info():
    """Получает информацию о текущем пользователе (без объекта БД)"""
    if not validate_session():
        return None
    
    with session_scope() as session:
        user = session.get(User, flask_session['user_id'])
        if user and user.is_active:
            return {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'role': user.role,
                'is_approved': user.is_approved
            }
    return None

def filter_students_by_tutor(query, session):
    """Фильтрует студентов по репетитору"""
    if not validate_session():
        return query.filter(Student.id == -1)  # Пустой результат для невалидной сессии
    
    user_role = flask_session.get('role')
    user_id = flask_session.get('user_id')
    
    if user_role == 'tutor':
        return query.filter(Student.tutor_id == user_id)
    return query  # Администратор видит всех

@contextmanager
def session_scope():
    """Контекстный менеджер для работы с сессией БД"""
    session = Session()
    try:
        yield session
        session.commit()
    except SQLAlchemyError as e:
        session.rollback()
        raise e
    finally:
        session.close()

def check_and_migrate_if_needed():
    """Проверяет и применяет миграции при необходимости"""
    try:
        # Пробуем выполнить простой запрос
        with session_scope() as session:
            # Проверяем доступность таблиц и связей
            session.query(Student).first()
            session.query(User).first()
        return True
    except (AmbiguousForeignKeysError, OperationalError) as e:
        print(f"\n⚠️ Обнаружена проблема с базой данных: {e}")
        print("🔧 Попытка автоматического исправления...")
        
        try:
            from migrate_db import quick_fix
            return quick_fix()
        except ImportError:
            print("❌ Модуль миграции не найден. Запустите migrate_db.py вручную.")
            return False
        except Exception as migration_error:
            print(f"❌ Ошибка миграции: {migration_error}")
            return False
    except Exception as e:
        print(f"❌ Неожиданная ошибка БД: {e}")
        return False

@app.context_processor
def inject_pending_homeworks_count():
    """Добавляет количество ожидающих проверки домашних заданий в контекст всех шаблонов"""
    context = {'pending_homeworks_count': 0}
    
    if flask_session.get('role') in ['admin', 'tutor']:
        try:
            with session_scope() as session:
                pending_count = session.query(Homework).filter(
                    Homework.submitted_date.isnot(None),
                    Homework.is_confirmed_by_tutor == False
                ).count()
                context['pending_homeworks_count'] = pending_count
        except:
            pass
    
    # Добавляем информацию о разрешениях
    context['can_create_courses'] = can_create_courses()
    
    return context

def validate_session():
    """Проверяет валидность текущей сессии"""
    if 'user_id' not in flask_session:
        return False
    
    try:
        with session_scope() as session:
            user = session.get(User, flask_session['user_id'])
            if not user:
                # Пользователь не существует в БД - очищаем сессию
                flask_session.clear()
                return False
            
            # Проверяем соответствие данных в сессии
            if (flask_session.get('username') != user.username or 
                flask_session.get('role') != user.role):
                # Данные не совпадают - очищаем сессию
                flask_session.clear()
                return False
            
            # Проверяем, активен ли пользователь
            if not user.is_active:
                flask_session.clear()
                return False
            
            # Проверяем токен сессии (если есть)
            session_token = flask_session.get('session_token')
            if session_token and user.reset_token != session_token:
                # Токен не совпадает - возможно пользователь вошел с другого устройства
                flask_session.clear()
                return False
            
            # Проверяем время жизни сессии (максимум 24 часа)
            login_time_str = flask_session.get('login_time')
            if login_time_str:
                try:
                    login_time = datetime.fromisoformat(login_time_str)
                    if (datetime.now() - login_time).total_seconds() > 24 * 3600:  # 24 часа
                        flask_session.clear()
                        return False
                except:
                    flask_session.clear()
                    return False
                
            return True
    except Exception as e:
        print(f"⚠️ Ошибка валидации сессии: {e}")
        flask_session.clear()
        return False

@app.before_request
def require_login():
    allowed = ['login', 'register', 'forgot_password', 'reset_password', 'static']
    
    if request.endpoint not in allowed:
        if 'user_id' not in flask_session:
            return redirect(url_for('login'))
        
        # Валидируем сессию
        if not validate_session():
            flash('Ваша сессия истекла или недействительна. Войдите снова.', 'warning')
            return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        with session_scope() as session:
            user = session.query(User).filter_by(username=username).first()
            
            if user and user.check_password(password) and user.is_active:
                # Проверяем одобрение для репетиторов
                if user.role == 'tutor' and not user.is_approved:
                    flash('Ваш аккаунт ожидает одобрения администратора', 'error')
                    return render_template('login.html')
                
                # Генерируем токен сессии для дополнительной безопасности
                import uuid
                session_token = str(uuid.uuid4())
                
                flask_session['user_id'] = user.id
                flask_session['username'] = user.username
                flask_session['role'] = user.role
                flask_session['logged_in'] = True
                flask_session['session_token'] = session_token
                flask_session['login_time'] = datetime.now().isoformat()
                
                if user.role == 'student':
                    flask_session['student_id'] = user.student_id
                
                # Сохраняем токен сессии в БД (для возможности отзыва)
                user.reset_token = session_token  # Используем это поле временно
                session.commit()
                
                flash(f'Добро пожаловать, {user.username}!', 'success')
                return redirect(url_for('index'))
            else:
                flash('Неверный логин или пароль', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Безопасный выход с очисткой токена"""
    user_id = flask_session.get('user_id')
    
    # Очищаем токен в БД
    if user_id:
        try:
            with session_scope() as session:
                user = session.get(User, user_id)
                if user:
                    user.reset_token = None  # Очищаем токен сессии
                    session.commit()
        except Exception as e:
            print(f"⚠️ Ошибка очистки токена при выходе: {e}")
    
    # Очищаем сессию
    flask_session.clear()
    flash('Вы успешно вышли из системы', 'info')
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
@app.route('/register/<token>', methods=['GET', 'POST'])
def register(token=None):
    invitation = None
    
    # Проверяем приглашение, если есть токен
    if token:
        with session_scope() as session:
            invitation = session.query(Invitation).filter_by(token=token, is_used=False).first()
            if not invitation or invitation.is_expired():
                flash('Недействительная или истекшая ссылка приглашения', 'error')
                return redirect(url_for('login'))
    
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        # Определяем роль
        if invitation:
            role = invitation.role
            # Проверяем, что email совпадает с приглашением
            if email != invitation.email:
                flash('Email должен совпадать с указанным в приглашении', 'error')
                return render_template('register.html', invitation=invitation)
        else:
            # Без приглашения можно создать только аккаунт репетитора
            role = 'tutor'
        
        # Валидация
        if password != confirm_password:
            flash('Пароли не совпадают', 'error')
            return render_template('register.html', invitation=invitation)
        
        if len(password) < 6:
            flash('Пароль должен содержать минимум 6 символов', 'error')
            return render_template('register.html', invitation=invitation)
        
        with session_scope() as session:
            # Проверяем уникальность
            if session.query(User).filter_by(username=username).first():
                flash('Пользователь с таким логином уже существует', 'error')
                return render_template('register.html', invitation=invitation)
            
            if session.query(User).filter_by(email=email).first():
                flash('Пользователь с таким email уже существует', 'error')
                return render_template('register.html', invitation=invitation)
            
            # Создаем пользователя
            user = User(username=username, email=email, role=role)
            user.set_password(password)
            
            # Настройки в зависимости от роли
            if role == 'tutor':
                user.is_approved = False  # Репетиторы требуют одобрения
                flash('Регистрация успешна! Ваш аккаунт будет активирован после одобрения администратором.', 'info')
            elif role == 'student' and invitation:
                user.is_approved = True
                user.student_id = invitation.student_id
                # Отмечаем приглашение как использованное
                invitation.is_used = True
                flash('Регистрация успешна! Теперь вы можете войти в систему.', 'success')
            
            session.add(user)
            session.commit()
            
            return redirect(url_for('login'))
    
    return render_template('register.html', invitation=invitation)

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        
        with session_scope() as session:
            user = session.query(User).filter_by(email=email).first()
            
            if user:
                token = user.generate_reset_token()
                session.commit()
                
                # Отправляем email с токеном
                reset_url = url_for('reset_password', token=token, _external=True)
                subject = "Восстановление пароля - TutorApp"
                body = f"""
                <h2>Восстановление пароля</h2>
                <p>Для сброса пароля перейдите по ссылке:</p>
                <a href="{reset_url}">Сбросить пароль</a>
                <p>Ссылка действительна в течение 1 часа.</p>
                """
                
                if send_email(email, subject, body):
                    flash('Ссылка для восстановления пароля отправлена на ваш email', 'success')
                else:
                    flash('Ошибка отправки email. Попробуйте позже.', 'error')
            else:
                flash('Пользователь с таким email не найден', 'error')
    
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    with session_scope() as session:
        user = session.query(User).filter_by(reset_token=token).first()
        
        if not user or not user.reset_token_expires or user.reset_token_expires < datetime.now():
            flash('Недействительная или истекшая ссылка для сброса пароля', 'error')
            return redirect(url_for('forgot_password'))
        
        if request.method == 'POST':
            password = request.form['password']
            confirm_password = request.form['confirm_password']
            
            if password != confirm_password:
                flash('Пароли не совпадают', 'error')
                return render_template('reset_password.html')
            
            if len(password) < 6:
                flash('Пароль должен содержать минимум 6 символов', 'error')
                return render_template('reset_password.html')
            
            user.set_password(password)
            user.reset_token = None
            user.reset_token_expires = None
            session.commit()
            
            flash('Пароль успешно изменен! Теперь вы можете войти в систему.', 'success')
            return redirect(url_for('login'))
    
    return render_template('reset_password.html')

@app.route('/settings', methods=['GET', 'POST'])
def user_settings():
    with session_scope() as session:
        current_user = session.get(User, flask_session['user_id'])
        
        if request.method == 'POST':
            # Обновление токена бота (только для репетиторов и администраторов)
            if current_user.role in ['admin', 'tutor']:
                bot_token = request.form.get('bot_token', '').strip()
                if bot_token:
                    current_user.bot_token = bot_token
                elif 'bot_token' in request.form:  # Если поле есть, но пустое
                    current_user.bot_token = None
            
            # Смена пароля
            current_password = request.form.get('current_password', '').strip()
            new_password = request.form.get('new_password', '').strip()
            confirm_password = request.form.get('confirm_password', '').strip()
            
            if current_password and new_password and confirm_password:
                if not current_user.check_password(current_password):
                    flash('Неверный текущий пароль', 'error')
                    return render_template('user_settings.html', current_user=current_user)
                
                if new_password != confirm_password:
                    flash('Новые пароли не совпадают', 'error')
                    return render_template('user_settings.html', current_user=current_user)
                
                if len(new_password) < 6:
                    flash('Новый пароль должен содержать минимум 6 символов', 'error')
                    return render_template('user_settings.html', current_user=current_user)
                
                current_user.set_password(new_password)
                flash('Пароль успешно изменен', 'success')
            
            session.commit()
            flash('Настройки сохранены', 'success')
            return redirect(url_for('user_settings'))
        
        return render_template('user_settings.html', current_user=current_user)

@app.route('/student_settings', methods=['GET', 'POST'])
@role_required('student')
def student_settings():
    """Настройки для студентов"""
    with session_scope() as session:
        current_user = session.get(User, flask_session['user_id'])
        
        if request.method == 'POST':
            # Обновляем email
            new_email = request.form.get('email', '').strip()
            if new_email and new_email != current_user.email:
                # Проверяем, не занят ли новый email
                existing_user = session.query(User).filter(
                    User.email == new_email,
                    User.id != current_user.id
                ).first()
                
                if existing_user:
                    flash('Email уже используется другим пользователем', 'error')
                    return render_template('student_settings.html', current_user=current_user)
                
                current_user.email = new_email
                current_user.username = new_email  # Обновляем логин тоже
            
            # Обновляем настройки уведомлений студента (но НЕ Chat ID)
            if current_user.student:
                current_user.student.receive_notifications = 'receive_notifications' in request.form
            
            # Проверяем смену пароля
            current_password = request.form.get('current_password', '').strip()
            new_password = request.form.get('new_password', '').strip()
            confirm_password = request.form.get('confirm_password', '').strip()
            
            if current_password or new_password or confirm_password:
                if not current_password:
                    flash('Для смены пароля введите текущий пароль', 'error')
                    return render_template('student_settings.html', current_user=current_user)
                
                if not current_user.check_password(current_password):
                    flash('Неверный текущий пароль', 'error')
                    return render_template('student_settings.html', current_user=current_user)
                
                if new_password != confirm_password:
                    flash('Новые пароли не совпадают', 'error')
                    return render_template('student_settings.html', current_user=current_user)
                
                if len(new_password) < 6:
                    flash('Новый пароль должен содержать минимум 6 символов', 'error')
                    return render_template('student_settings.html', current_user=current_user)
                
                current_user.set_password(new_password)
                flash('Пароль успешно изменен', 'success')
            
            session.commit()
            flash('Настройки сохранены', 'success')
            return redirect(url_for('student_settings'))
        
        return render_template('student_settings.html', current_user=current_user)

@app.route('/admin/security')
@role_required('admin')
def admin_security():
    """Административная панель безопасности"""
    with session_scope() as session:
        # Получаем активные сессии (пользователей с токенами)
        active_sessions = session.query(User).filter(
            User.reset_token.isnot(None),
            User.is_active == True
        ).all()
        
        return render_template('admin_security.html', active_sessions=active_sessions)

@app.route('/admin/revoke_session/<int:user_id>', methods=['POST'])
@role_required('admin')
def revoke_user_session(user_id):
    """Отзыв сессии пользователя"""
    with session_scope() as session:
        user = session.get(User, user_id)
        if user:
            user.reset_token = None  # Очищаем токен сессии
            session.commit()
            flash(f'Сессия пользователя {user.username} отозвана', 'success')
        else:
            flash('Пользователь не найден', 'error')
    
    return redirect(url_for('admin_security'))

@app.route('/admin/system_settings', methods=['GET', 'POST'])
@role_required('admin')
def system_settings():
    """Системные настройки (только для администраторов)"""
    with session_scope() as session:
        if request.method == 'POST':
            # Обновляем глобальный токен бота в config.py
            bot_token = request.form.get('bot_token', '').strip()
            
            if bot_token:
                # Записываем токен в файл config.py
                try:
                    config_path = os.path.join(os.path.dirname(__file__), 'config.py')
                    with open(config_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Заменяем токен в файле
                    import re
                    content = re.sub(
                        r'BOT_TOKEN\s*=\s*["\'][^"\']*["\']',
                        f'BOT_TOKEN = "{bot_token}"',
                        content
                    )
                    
                    with open(config_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    
                    flash('Токен бота обновлен в системных настройках', 'success')
                    
                except Exception as e:
                    flash(f'Ошибка обновления токена: {e}', 'error')
            
            return redirect(url_for('system_settings'))
        
        # Получаем текущий токен из config
        import config
        current_token = getattr(config, 'BOT_TOKEN', '')
        
        return render_template('system_settings.html', current_token=current_token)

# ==================== СИСТЕМА КУРСОВ ====================

@app.route('/courses')
@role_required('admin', 'tutor')
def courses_list():
    """Список курсов"""
    current_user_info = get_current_user_info()
    
    with session_scope() as session:
        if current_user_info['role'] == 'admin':
            # Админ видит все курсы
            courses = session.query(Course).order_by(Course.created_at.desc()).all()
        else:
            # Репетитор видит только свои курсы
            courses = session.query(Course).filter_by(tutor_id=current_user_info['id']).order_by(Course.created_at.desc()).all()
        
        return render_template('courses_list.html', courses=courses)

def can_create_courses():
    """Проверяет, может ли текущий пользователь создавать курсы"""
    if not validate_session():
        return False
    
    user_role = flask_session.get('role')
    user_id = flask_session.get('user_id')
    
    # Администраторы всегда могут
    if user_role == 'admin':
        return True
    
    # Для репетиторов проверяем разрешение
    if user_role == 'tutor':
        with session_scope() as session:
            user = session.get(User, user_id)
            return user and user.can_create_courses
    
    return False

@app.route('/courses/create', methods=['GET', 'POST'])
@role_required('tutor')
def create_course():
    """Создание нового курса"""
    # Проверяем разрешение на создание курсов
    if not can_create_courses():
        flash('У вас нет прав на создание курсов. Обратитесь к администратору.', 'error')
        return redirect(url_for('courses_list'))
    
    current_user_info = get_current_user_info()
    
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        
        if not title:
            flash('Название курса обязательно', 'error')
            return render_template('create_course.html')
        
        with session_scope() as session:
            course = Course(
                title=title,
                description=description,
                tutor_id=current_user_info['id']
            )
            session.add(course)
            session.commit()
            
            flash(f'Курс "{title}" создан успешно!', 'success')
            return redirect(url_for('course_detail', course_id=course.id))
    
    return render_template('create_course.html')

@app.route('/courses/<int:course_id>')
@role_required('admin', 'tutor')
def course_detail(course_id):
    """Детали курса с модулями и уроками"""
    current_user_info = get_current_user_info()
    
    with session_scope() as session:
        course = session.get(Course, course_id)
        
        if not course:
            flash('Курс не найден', 'error')
            return redirect(url_for('courses_list'))
        
        # Проверяем права доступа
        if current_user_info['role'] != 'admin' and course.tutor_id != current_user_info['id']:
            flash('У вас нет доступа к этому курсу', 'error')
            return redirect(url_for('courses_list'))
        
        # Получаем модули с уроками
        modules = session.query(CourseModule).filter_by(
            course_id=course_id, is_active=True
        ).order_by(CourseModule.order_index).all()
        
        # Получаем статистику студентов
        enrollments_count = session.query(CourseEnrollment).filter_by(
            course_id=course_id, is_active=True
        ).count()
        
        return render_template('course_detail.html', 
                             course=course, 
                             modules=modules, 
                             enrollments_count=enrollments_count)

@app.route('/courses/<int:course_id>/modules/create', methods=['GET', 'POST'])
@role_required('tutor')
def create_module(course_id):
    """Создание модуля курса"""
    # Проверяем разрешение на создание/редактирование курсов
    if not can_create_courses():
        flash('У вас нет прав на редактирование курсов', 'error')
        return redirect(url_for('courses_list'))
    
    current_user_info = get_current_user_info()
    
    with session_scope() as session:
        course = session.get(Course, course_id)
        
        if not course or course.tutor_id != current_user_info['id']:
            flash('Курс не найден или нет доступа', 'error')
            return redirect(url_for('courses_list'))
        
        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            
            if not title:
                flash('Название модуля обязательно', 'error')
                return render_template('create_module.html', course=course)
            
            # Определяем порядковый номер
            max_order = session.query(CourseModule).filter_by(course_id=course_id).count()
            
            module = CourseModule(
                course_id=course_id,
                title=title,
                description=description,
                order_index=max_order + 1
            )
            session.add(module)
            session.commit()
            
            flash(f'Модуль "{title}" создан успешно!', 'success')
            return redirect(url_for('course_detail', course_id=course_id))
        
        return render_template('create_module.html', course=course)

@app.route('/modules/<int:module_id>/lessons/create', methods=['GET', 'POST'])
@role_required('tutor')
def create_lesson(module_id):
    """Создание урока модуля"""
    # Проверяем разрешение на создание/редактирование курсов
    if not can_create_courses():
        flash('У вас нет прав на редактирование курсов', 'error')
        return redirect(url_for('courses_list'))
    
    current_user_info = get_current_user_info()
    
    with session_scope() as session:
        module = session.get(CourseModule, module_id)
        
        if not module:
            flash('Модуль не найден', 'error')
            return redirect(url_for('courses_list'))
        
        # Проверяем права доступа через курс
        course = session.get(Course, module.course_id)
        if not course or course.tutor_id != current_user_info['id']:
            flash('Нет доступа к этому модулю', 'error')
            return redirect(url_for('courses_list'))
        
        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            content = request.form.get('content', '').strip()
            
            if not title:
                flash('Название урока обязательно', 'error')
                return render_template('create_lesson.html', module=module, course=course)
            
            # Определяем порядковый номер
            max_order = session.query(CourseLesson).filter_by(module_id=module_id).count()
            
            lesson = CourseLesson(
                module_id=module_id,
                title=title,
                content=content,
                order_index=max_order + 1
            )
            session.add(lesson)
            session.commit()
            
            flash(f'Урок "{title}" создан успешно!', 'success')
            return redirect(url_for('course_detail', course_id=course.id))
        
        return render_template('create_lesson.html', module=module, course=course)

@app.route('/lessons/<int:lesson_id>')
@role_required('admin', 'tutor')
def lesson_detail(lesson_id):
    """Детали урока"""
    current_user_info = get_current_user_info()
    
    with session_scope() as session:
        lesson = session.get(CourseLesson, lesson_id)
        
        if not lesson:
            flash('Урок не найден', 'error')
            return redirect(url_for('courses_list'))
        
        # Получаем модуль и курс для проверки прав
        module = session.get(CourseModule, lesson.module_id)
        course = session.get(Course, module.course_id)
        
        # Проверяем права доступа
        if current_user_info['role'] != 'admin' and course.tutor_id != current_user_info['id']:
            flash('У вас нет доступа к этому уроку', 'error')
            return redirect(url_for('courses_list'))
        
        # Получаем материалы урока
        materials = session.query(CourseMaterial).filter_by(lesson_id=lesson_id).all()
        
        # Получаем задания урока
        assignments = session.query(CourseAssignment).filter_by(lesson_id=lesson_id).all()
        
        # Получаем блоки урока
        blocks = session.query(LessonBlock).filter_by(lesson_id=lesson_id).order_by(LessonBlock.order_index).all()
        
        return render_template('lesson_detail.html', 
                             lesson=lesson, 
                             module=module,
                             course=course,
                             materials=materials,
                             assignments=assignments,
                             blocks=blocks)

@app.route('/lessons/<int:lesson_id>/materials/add', methods=['GET', 'POST'])
@role_required('tutor')
def add_material(lesson_id):
    """Добавление материала к уроку"""
    # Проверяем разрешение на создание/редактирование курсов
    if not can_create_courses():
        flash('У вас нет прав на редактирование курсов', 'error')
        return redirect(url_for('courses_list'))
    
    current_user_info = get_current_user_info()
    
    with session_scope() as session:
        lesson = session.get(CourseLesson, lesson_id)
        
        if not lesson:
            flash('Урок не найден', 'error')
            return redirect(url_for('courses_list'))
        
        # Проверяем права доступа через курс
        module = session.get(CourseModule, lesson.module_id)
        course = session.get(Course, module.course_id)
        
        if not course or course.tutor_id != current_user_info['id']:
            flash('Нет доступа к этому уроку', 'error')
            return redirect(url_for('courses_list'))
        
        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            url = request.form.get('url', '').strip()
            description = request.form.get('description', '').strip()
            
            if not title or not url:
                flash('Название и ссылка обязательны', 'error')
                return render_template('add_material.html', lesson=lesson, module=module, course=course)
            
            # Определяем тип материала по URL
            material_type = determine_material_type(url)
            
            material = CourseMaterial(
                lesson_id=lesson_id,
                title=title,
                material_type=material_type,
                file_path=url,  # Используем file_path для хранения URL
                original_filename=description if description else title
            )
            session.add(material)
            session.commit()
            
            flash(f'Материал "{title}" добавлен успешно!', 'success')
            return redirect(url_for('lesson_detail', lesson_id=lesson_id))
        
        return render_template('add_material.html', lesson=lesson, module=module, course=course)

def determine_material_type(url):
    """Определяет тип материала по URL"""
    url_lower = url.lower()
    
    if 'docs.google.com/presentation' in url_lower:
        return 'presentation'
    elif 'docs.google.com/document' in url_lower:
        return 'document'
    elif 'docs.google.com/spreadsheets' in url_lower:
        return 'spreadsheet'
    elif 'drive.google.com' in url_lower:
        return 'drive_file'
    elif 'youtube.com' in url_lower or 'youtu.be' in url_lower:
        return 'video'
    elif 'vimeo.com' in url_lower:
        return 'video'
    elif any(ext in url_lower for ext in ['.pdf', '.doc', '.docx']):
        return 'document'
    elif any(ext in url_lower for ext in ['.jpg', '.jpeg', '.png', '.gif']):
        return 'image'
    elif any(ext in url_lower for ext in ['.mp4', '.avi', '.mov']):
        return 'video'
    else:
        return 'link'

# ==================== УПРАВЛЕНИЕ БЛОКАМИ УРОКА ====================

@app.route('/lessons/<int:lesson_id>/blocks/add', methods=['GET', 'POST'])
@role_required('tutor')
def add_text_block(lesson_id):
    """Добавление текстового блока к уроку"""
    current_user_info = get_current_user_info()
    
    with session_scope() as session:
        lesson = session.get(CourseLesson, lesson_id)
        
        if not lesson:
            flash('Урок не найден', 'error')
            return redirect(url_for('courses_list'))
        
        # Проверяем права доступа через курс
        module = session.get(CourseModule, lesson.module_id)
        course = session.get(Course, module.course_id)
        
        if not course or course.tutor_id != current_user_info['id']:
            flash('Нет доступа к этому уроку', 'error')
            return redirect(url_for('courses_list'))
        
        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            content = request.form.get('content', '').strip()
            
            if not content:
                flash('Содержимое блока обязательно', 'error')
                return render_template('add_text_block.html', lesson=lesson, module=module, course=course)
            
            # Определяем порядковый номер
            max_order = session.query(LessonBlock).filter_by(lesson_id=lesson_id).count()
            
            block = LessonBlock(
                lesson_id=lesson_id,
                block_type='text',
                title=title if title else None,
                content=content,
                order_index=max_order + 1
            )
            session.add(block)
            session.commit()
            
            flash('Текстовый блок добавлен успешно!', 'success')
            return redirect(url_for('lesson_detail', lesson_id=lesson_id))
        
        return render_template('add_text_block.html', lesson=lesson, module=module, course=course)

@app.route('/lessons/<int:lesson_id>/blocks/<int:block_id>/edit', methods=['GET', 'POST'])
@role_required('tutor')
def edit_text_block(lesson_id, block_id):
    """Редактирование текстового блока"""
    current_user_info = get_current_user_info()
    
    with session_scope() as session:
        block = session.get(LessonBlock, block_id)
        
        if not block or block.lesson_id != lesson_id:
            flash('Блок не найден', 'error')
            return redirect(url_for('courses_list'))
        
        lesson = session.get(CourseLesson, lesson_id)
        module = session.get(CourseModule, lesson.module_id)
        course = session.get(Course, module.course_id)
        
        if not course or course.tutor_id != current_user_info['id']:
            flash('Нет доступа к этому блоку', 'error')
            return redirect(url_for('courses_list'))
        
        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            content = request.form.get('content', '').strip()
            
            if not content:
                flash('Содержимое блока обязательно', 'error')
                return render_template('edit_text_block.html', block=block, lesson=lesson, module=module, course=course)
            
            block.title = title if title else None
            block.content = content
            session.commit()
            
            flash('Блок обновлен успешно!', 'success')
            return redirect(url_for('lesson_detail', lesson_id=lesson_id))
        
        return render_template('edit_text_block.html', block=block, lesson=lesson, module=module, course=course)

@app.route('/lessons/<int:lesson_id>/blocks/<int:block_id>/delete', methods=['POST'])
@role_required('tutor')
def delete_text_block(lesson_id, block_id):
    """Удаление текстового блока"""
    current_user_info = get_current_user_info()
    
    with session_scope() as session:
        block = session.get(LessonBlock, block_id)
        
        if not block or block.lesson_id != lesson_id:
            flash('Блок не найден', 'error')
            return redirect(url_for('lesson_detail', lesson_id=lesson_id))
        
        lesson = session.get(CourseLesson, lesson_id)
        module = session.get(CourseModule, lesson.module_id)
        course = session.get(Course, module.course_id)
        
        if not course or course.tutor_id != current_user_info['id']:
            flash('Нет доступа к этому блоку', 'error')
            return redirect(url_for('lesson_detail', lesson_id=lesson_id))
        
        session.delete(block)
        session.commit()
        
        flash('Блок удален успешно!', 'success')
        return redirect(url_for('lesson_detail', lesson_id=lesson_id))

@app.route('/lessons/<int:lesson_id>/blocks/reorder', methods=['POST'])
@role_required('tutor')
def reorder_blocks(lesson_id):
    """Изменение порядка блоков"""
    current_user_info = get_current_user_info()
    
    with session_scope() as session:
        lesson = session.get(CourseLesson, lesson_id)
        
        if not lesson:
            return {'success': False, 'message': 'Урок не найден'}
        
        module = session.get(CourseModule, lesson.module_id)
        course = session.get(Course, module.course_id)
        
        if not course or course.tutor_id != current_user_info['id']:
            return {'success': False, 'message': 'Нет доступа'}
        
        block_ids = request.json.get('block_ids', [])
        
        for index, block_id in enumerate(block_ids):
            block = session.get(LessonBlock, block_id)
            if block and block.lesson_id == lesson_id:
                block.order_index = index + 1
        
        session.commit()
        return {'success': True}

# ==================== УПРАВЛЕНИЕ ЗАДАНИЯМИ ====================

@app.route('/lessons/<int:lesson_id>/assignments/add', methods=['GET', 'POST'])
@role_required('tutor')
def add_assignment(lesson_id):
    """Добавление задания к уроку"""
    # Проверяем разрешение на создание/редактирование курсов
    if not can_create_courses():
        flash('У вас нет прав на редактирование курсов', 'error')
        return redirect(url_for('courses_list'))
    
    current_user_info = get_current_user_info()
    
    with session_scope() as session:
        lesson = session.get(CourseLesson, lesson_id)
        
        if not lesson:
            flash('Урок не найден', 'error')
            return redirect(url_for('courses_list'))
        
        # Проверяем права доступа через курс
        module = session.get(CourseModule, lesson.module_id)
        course = session.get(Course, module.course_id)
        
        if not course or course.tutor_id != current_user_info['id']:
            flash('Нет доступа к этому уроку', 'error')
            return redirect(url_for('courses_list'))
        
        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            assignment_type = request.form.get('assignment_type', 'text')
            is_required = request.form.get('is_required') == 'on'
            max_points = request.form.get('max_points', 100)
            
            if not title or not description:
                flash('Название и описание задания обязательны', 'error')
                return render_template('add_assignment.html', lesson=lesson, module=module, course=course)
            
            try:
                max_points = int(max_points)
                if max_points < 1:
                    max_points = 1
            except ValueError:
                max_points = 100
            
            assignment = CourseAssignment(
                lesson_id=lesson_id,
                title=title,
                description=description,
                assignment_type=assignment_type,
                is_required=is_required,
                max_points=max_points
            )
            session.add(assignment)
            session.commit()
            
            flash(f'Задание "{title}" добавлено успешно!', 'success')
            return redirect(url_for('lesson_detail', lesson_id=lesson_id))
        
        return render_template('add_assignment.html', lesson=lesson, module=module, course=course)

@app.route('/assignments/<int:assignment_id>/edit', methods=['GET', 'POST'])
@role_required('tutor')
def edit_assignment(assignment_id):
    """Редактирование задания"""
    current_user_info = get_current_user_info()
    
    with session_scope() as session:
        assignment = session.get(CourseAssignment, assignment_id)
        
        if not assignment:
            flash('Задание не найдено', 'error')
            return redirect(url_for('courses_list'))
        
        lesson = session.get(CourseLesson, assignment.lesson_id)
        module = session.get(CourseModule, lesson.module_id)
        course = session.get(Course, module.course_id)
        
        if not course or course.tutor_id != current_user_info['id']:
            flash('Нет доступа к этому заданию', 'error')
            return redirect(url_for('courses_list'))
        
        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            assignment_type = request.form.get('assignment_type', 'text')
            is_required = request.form.get('is_required') == 'on'
            max_points = request.form.get('max_points', 100)
            
            if not title or not description:
                flash('Название и описание задания обязательны', 'error')
                return render_template('edit_assignment.html', assignment=assignment, lesson=lesson, module=module, course=course)
            
            try:
                max_points = int(max_points)
                if max_points < 1:
                    max_points = 1
            except ValueError:
                max_points = 100
            
            assignment.title = title
            assignment.description = description
            assignment.assignment_type = assignment_type
            assignment.is_required = is_required
            assignment.max_points = max_points
            session.commit()
            
            flash('Задание обновлено успешно!', 'success')
            return redirect(url_for('lesson_detail', lesson_id=lesson.id))
        
        return render_template('edit_assignment.html', assignment=assignment, lesson=lesson, module=module, course=course)

@app.route('/assignments/<int:assignment_id>/delete', methods=['POST'])
@role_required('tutor')
def delete_assignment(assignment_id):
    """Удаление задания"""
    current_user_info = get_current_user_info()
    
    with session_scope() as session:
        assignment = session.get(CourseAssignment, assignment_id)
        
        if not assignment:
            flash('Задание не найдено', 'error')
            return redirect(url_for('courses_list'))
        
        lesson = session.get(CourseLesson, assignment.lesson_id)
        module = session.get(CourseModule, lesson.module_id)
        course = session.get(Course, module.course_id)
        
        if not course or course.tutor_id != current_user_info['id']:
            flash('Нет доступа к этому заданию', 'error')
            return redirect(url_for('lesson_detail', lesson_id=lesson.id))
        
        session.delete(assignment)
        session.commit()
        
        flash('Задание удалено успешно!', 'success')
        return redirect(url_for('lesson_detail', lesson_id=lesson.id))

# ==================== УПРАВЛЕНИЕ СТУДЕНТАМИ КУРСА ====================

@app.route('/courses/<int:course_id>/students')
@role_required('tutor')
def course_students(course_id):
    """Управление студентами курса"""
    current_user_info = get_current_user_info()
    
    with session_scope() as session:
        course = session.get(Course, course_id)
        
        if not course or course.tutor_id != current_user_info['id']:
            flash('Курс не найден или нет доступа', 'error')
            return redirect(url_for('courses_list'))
        
        # Получаем записанных студентов
        enrollments = session.query(CourseEnrollment)\
            .filter_by(course_id=course_id)\
            .join(Student)\
            .order_by(CourseEnrollment.enrolled_at.desc())\
            .all()
        
        # Получаем всех студентов репетитора, которые еще не записаны на курс
        enrolled_student_ids = [e.student_id for e in enrollments]
        available_students = session.query(Student)\
            .filter(Student.tutor_id == current_user_info['id'])\
            .filter(~Student.id.in_(enrolled_student_ids) if enrolled_student_ids else True)\
            .all()
        
        return render_template('course_students.html',
                             course=course,
                             enrollments=enrollments,
                             available_students=available_students)

@app.route('/courses/<int:course_id>/students/add', methods=['POST'])
@role_required('tutor')
def add_student_to_course(course_id):
    """Добавить студента на курс"""
    current_user_info = get_current_user_info()
    
    with session_scope() as session:
        course = session.get(Course, course_id)
        
        if not course or course.tutor_id != current_user_info['id']:
            flash('Курс не найден или нет доступа', 'error')
            return redirect(url_for('courses_list'))
        
        student_id = request.form.get('student_id')
        if not student_id:
            flash('Выберите студента', 'error')
            return redirect(url_for('course_students', course_id=course_id))
        
        try:
            student_id = int(student_id)
        except ValueError:
            flash('Неверный ID студента', 'error')
            return redirect(url_for('course_students', course_id=course_id))
        
        # Проверяем, что студент принадлежит репетитору
        student = session.query(Student).filter_by(
            id=student_id,
            tutor_id=current_user_info['id']
        ).first()
        
        if not student:
            flash('Студент не найден', 'error')
            return redirect(url_for('course_students', course_id=course_id))
        
        # Проверяем, что студент еще не записан
        existing_enrollment = session.query(CourseEnrollment).filter_by(
            course_id=course_id,
            student_id=student_id
        ).first()
        
        if existing_enrollment:
            flash('Студент уже записан на этот курс', 'warning')
            return redirect(url_for('course_students', course_id=course_id))
        
        # Создаем запись
        enrollment = CourseEnrollment(
            course_id=course_id,
            student_id=student_id
        )
        session.add(enrollment)
        session.commit()
        
        flash(f'Студент {student.full_name} добавлен на курс!', 'success')
        return redirect(url_for('course_students', course_id=course_id))

@app.route('/courses/<int:course_id>/students/<int:student_id>/remove', methods=['POST'])
@role_required('tutor')
def remove_student_from_course(course_id, student_id):
    """Убрать студента с курса"""
    current_user_info = get_current_user_info()
    
    with session_scope() as session:
        course = session.get(Course, course_id)
        
        if not course or course.tutor_id != current_user_info['id']:
            flash('Курс не найден или нет доступа', 'error')
            return redirect(url_for('courses_list'))
        
        enrollment = session.query(CourseEnrollment).filter_by(
            course_id=course_id,
            student_id=student_id
        ).first()
        
        if not enrollment:
            flash('Студент не найден в курсе', 'error')
            return redirect(url_for('course_students', course_id=course_id))
        
        student_name = enrollment.student.full_name
        session.delete(enrollment)
        session.commit()
        
        flash(f'Студент {student_name} исключен из курса', 'success')
        return redirect(url_for('course_students', course_id=course_id))

@app.route('/courses/<int:course_id>/students/<int:student_id>/toggle', methods=['POST'])
@role_required('tutor')
def toggle_student_access(course_id, student_id):
    """Включить/выключить доступ студента к курсу"""
    current_user_info = get_current_user_info()
    
    with session_scope() as session:
        course = session.get(Course, course_id)
        
        if not course or course.tutor_id != current_user_info['id']:
            flash('Курс не найден или нет доступа', 'error')
            return redirect(url_for('courses_list'))
        
        enrollment = session.query(CourseEnrollment).filter_by(
            course_id=course_id,
            student_id=student_id
        ).first()
        
        if not enrollment:
            flash('Студент не найден в курсе', 'error')
            return redirect(url_for('course_students', course_id=course_id))
        
        enrollment.is_active = not enrollment.is_active
        session.commit()
        
        status = "включен" if enrollment.is_active else "отключен"
        flash(f'Доступ студента {enrollment.student.full_name} {status}', 'success')
        return redirect(url_for('course_students', course_id=course_id))

# ==================== АДМИН-ПАНЕЛЬ ====================

@app.route('/admin')
@role_required('admin')
def admin_panel():
    """Главная админ-панель"""
    with session_scope() as session:
        # Общая статистика
        tutors_count = session.query(User).filter_by(role='tutor').count()
        students_count = session.query(Student).count()
        courses_count = session.query(Course).count()
        lessons_count = session.query(Lesson).count()
        enrollments_count = session.query(CourseEnrollment).count()
        
        # Последние регистрации репетиторов
        recent_tutors = session.query(User)\
            .filter_by(role='tutor')\
            .order_by(User.id.desc())\
            .limit(5)\
            .all()
        
        # Последние курсы
        recent_courses = session.query(Course)\
            .join(User, Course.tutor_id == User.id)\
            .order_by(Course.created_at.desc())\
            .limit(5)\
            .all()
        
        return render_template('admin_panel.html',
                             tutors_count=tutors_count,
                             students_count=students_count,
                             courses_count=courses_count,
                             lessons_count=lessons_count,
                             enrollments_count=enrollments_count,
                             recent_tutors=recent_tutors,
                             recent_courses=recent_courses)

@app.route('/admin/tutors')
@role_required('admin')
def admin_tutors():
    """Управление репетиторами"""
    with session_scope() as session:
        tutors = session.query(User)\
            .filter_by(role='tutor')\
            .order_by(User.id.desc())\
            .all()
        
        # Получаем статистику для каждого репетитора
        tutors_data = []
        for tutor in tutors:
            students_count = session.query(Student)\
                .filter_by(tutor_id=tutor.id)\
                .count()
            
            courses_count = session.query(Course)\
                .filter_by(tutor_id=tutor.id)\
                .count()
            
            lessons_count = session.query(Lesson)\
                .join(Student, Lesson.student_id == Student.id)\
                .filter(Student.tutor_id == tutor.id)\
                .count()
            
            tutors_data.append({
                'tutor': tutor,
                'students_count': students_count,
                'courses_count': courses_count,
                'lessons_count': lessons_count
            })
        
        return render_template('admin_tutors.html', tutors_data=tutors_data)

@app.route('/admin/tutors/<int:tutor_id>')
@role_required('admin')
def admin_tutor_detail(tutor_id):
    """Детальная информация о репетиторе"""
    with session_scope() as session:
        tutor = session.get(User, tutor_id)
        
        if not tutor or tutor.role != 'tutor':
            flash('Репетитор не найден', 'error')
            return redirect(url_for('admin_tutors'))
        
        # Студенты репетитора
        students = session.query(Student)\
            .filter_by(tutor_id=tutor_id)\
            .order_by(Student.full_name)\
            .all()
        
        # Курсы репетитора
        courses = session.query(Course)\
            .filter_by(tutor_id=tutor_id)\
            .order_by(Course.created_at.desc())\
            .all()
        
        # Курсы с информацией о студентах
        courses_data = []
        for course in courses:
            enrollments = session.query(CourseEnrollment)\
                .filter_by(course_id=course.id)\
                .join(Student)\
                .all()
            
            modules_count = session.query(CourseModule)\
                .filter_by(course_id=course.id)\
                .count()
            
            lessons_count = session.query(CourseLesson)\
                .join(CourseModule, CourseLesson.module_id == CourseModule.id)\
                .filter(CourseModule.course_id == course.id)\
                .count()
            
            courses_data.append({
                'course': course,
                'enrollments': enrollments,
                'modules_count': modules_count,
                'lessons_count': lessons_count
            })
        
        # Последние уроки
        recent_lessons = session.query(Lesson)\
            .join(Student, Lesson.student_id == Student.id)\
            .filter(Student.tutor_id == tutor_id)\
            .order_by(Lesson.date_time.desc())\
            .limit(10)\
            .all()
        
        return render_template('admin_tutor_detail.html',
                             tutor=tutor,
                             students=students,
                             courses_data=courses_data,
                             recent_lessons=recent_lessons)

@app.route('/admin/courses')
@role_required('admin')
def admin_courses():
    """Управление курсами"""
    with session_scope() as session:
        courses = session.query(Course)\
            .join(User, Course.tutor_id == User.id)\
            .order_by(Course.created_at.desc())\
            .all()
        
        courses_data = []
        for course in courses:
            enrollments_count = session.query(CourseEnrollment)\
                .filter_by(course_id=course.id)\
                .count()
            
            modules_count = session.query(CourseModule)\
                .filter_by(course_id=course.id)\
                .count()
            
            lessons_count = session.query(CourseLesson)\
                .join(CourseModule, CourseLesson.module_id == CourseModule.id)\
                .filter(CourseModule.course_id == course.id)\
                .count()
            
            courses_data.append({
                'course': course,
                'enrollments_count': enrollments_count,
                'modules_count': modules_count,
                'lessons_count': lessons_count
            })
        
        return render_template('admin_courses.html', courses_data=courses_data)

@app.route('/admin/tutors/<int:tutor_id>/toggle', methods=['POST'])
@role_required('admin')
def admin_toggle_tutor(tutor_id):
    """Активировать/деактивировать репетитора"""
    with session_scope() as session:
        tutor = session.get(User, tutor_id)
        
        if not tutor or tutor.role != 'tutor':
            flash('Репетитор не найден', 'error')
            return redirect(url_for('admin_tutors'))
        
        # Переключаем одобрение
        tutor.is_approved = not tutor.is_approved
        session.commit()
        
        status = "одобрен" if tutor.is_approved else "заблокирован"
        flash(f'Репетитор {tutor.username} {status}', 'success')
        return redirect(url_for('admin_tutor_detail', tutor_id=tutor_id))

# ==================== СТУДЕНТСКИЕ КУРСЫ ====================

@app.route('/student/courses')
@role_required('student')
def student_courses():
    """Курсы студента"""
    with session_scope() as session:
        student_id = flask_session.get('student_id')
        if not student_id:
            flash('Студент не найден', 'error')
            return redirect(url_for('student_dashboard'))
        
        # Получаем записи студента на курсы
        enrollments = session.query(CourseEnrollment)\
            .filter_by(student_id=student_id, is_active=True)\
            .join(Course)\
            .order_by(Course.title)\
            .all()
        
        return render_template('student_courses.html', enrollments=enrollments)

@app.route('/student/courses/<int:course_id>')
@role_required('student')
def student_course_detail(course_id):
    """Детальный просмотр курса для студента"""
    with session_scope() as session:
        student_id = flask_session.get('student_id')
        if not student_id:
            flash('Студент не найден', 'error')
            return redirect(url_for('student_dashboard'))
        
        # Проверяем, записан ли студент на курс
        enrollment = session.query(CourseEnrollment)\
            .filter_by(course_id=course_id, student_id=student_id, is_active=True)\
            .first()
        
        if not enrollment:
            flash('У вас нет доступа к этому курсу', 'error')
            return redirect(url_for('student_courses'))
        
        course = enrollment.course
        
        # Получаем все модули и уроки курса
        modules = session.query(CourseModule)\
            .filter_by(course_id=course_id)\
            .order_by(CourseModule.order_index)\
            .all()
        
        # Для каждого модуля получаем уроки
        modules_data = []
        for module in modules:
            lessons = session.query(CourseLesson)\
                .filter_by(module_id=module.id)\
                .order_by(CourseLesson.order_index)\
                .all()
            
            # Проверяем доступ к каждому уроку
            lessons_data = []
            for lesson in lessons:
                can_access = enrollment.can_access_lesson(lesson.id)
                is_completed = lesson.id in enrollment.get_completed_lesson_ids()
                is_current = lesson.id == enrollment.current_lesson_id
                
                lessons_data.append({
                    'lesson': lesson,
                    'can_access': can_access,
                    'is_completed': is_completed,
                    'is_current': is_current
                })
            
            modules_data.append({
                'module': module,
                'lessons': lessons_data
            })
        
        return render_template('student_course_detail.html', 
                             course=course,
                             enrollment=enrollment,
                             modules_data=modules_data)

@app.route('/student/lessons/<int:lesson_id>')
@role_required('student')
def student_lesson_view(lesson_id):
    """Просмотр урока студентом"""
    with session_scope() as session:
        student_id = flask_session.get('student_id')
        if not student_id:
            flash('Студент не найден', 'error')
            return redirect(url_for('student_dashboard'))
        
        lesson = session.get(CourseLesson, lesson_id)
        if not lesson:
            flash('Урок не найден', 'error')
            return redirect(url_for('student_courses'))
        
        # Проверяем, записан ли студент на курс
        enrollment = session.query(CourseEnrollment)\
            .filter_by(course_id=lesson.module.course_id, student_id=student_id, is_active=True)\
            .first()
        
        if not enrollment:
            flash('У вас нет доступа к этому курсу', 'error')
            return redirect(url_for('student_courses'))
        
        # Проверяем доступ к уроку
        if not enrollment.can_access_lesson(lesson_id):
            flash('У вас пока нет доступа к этому уроку', 'warning')
            return redirect(url_for('student_course_detail', course_id=lesson.module.course_id))
        
        # Получаем блоки урока
        blocks = session.query(LessonBlock)\
            .filter_by(lesson_id=lesson_id)\
            .order_by(LessonBlock.order_index)\
            .all()
        
        # Получаем задания урока
        assignments = session.query(CourseAssignment)\
            .filter_by(lesson_id=lesson_id)\
            .order_by(CourseAssignment.id)\
            .all()
        
        # Получаем существующие ответы студента
        submissions = {}
        for assignment in assignments:
            submission = session.query(CourseSubmission)\
                .filter_by(assignment_id=assignment.id, enrollment_id=enrollment.id)\
                .first()
            submissions[assignment.id] = submission
        
        # Проверяем, можно ли завершить урок
        can_complete = True
        if assignments:
            # Если есть задания, нужно проверить их выполнение
            for assignment in assignments:
                submission = submissions.get(assignment.id)
                if not submission or not submission.is_approved():
                    can_complete = False
                    break
        
        is_completed = lesson_id in enrollment.get_completed_lesson_ids()
        
        return render_template('student_lesson_view.html',
                             lesson=lesson,
                             course=lesson.module.course,
                             enrollment=enrollment,
                             blocks=blocks,
                             assignments=assignments,
                             submissions=submissions,
                             can_complete=can_complete,
                             is_completed=is_completed)

@app.route('/student/lessons/<int:lesson_id>/submit', methods=['POST'])
@role_required('student')
def student_submit_assignment(lesson_id):
    """Отправка задания студентом"""
    with session_scope() as session:
        student_id = flask_session.get('student_id')
        assignment_id = request.form.get('assignment_id')
        content = request.form.get('content', '').strip()
        
        if not assignment_id or not content:
            flash('Необходимо выбрать задание и заполнить ответ', 'error')
            return redirect(url_for('student_lesson_view', lesson_id=lesson_id))
        
        # Проверяем доступ
        lesson = session.get(CourseLesson, lesson_id)
        enrollment = session.query(CourseEnrollment)\
            .filter_by(course_id=lesson.module.course_id, student_id=student_id, is_active=True)\
            .first()
        
        if not enrollment or not enrollment.can_access_lesson(lesson_id):
            flash('У вас нет доступа к этому уроку', 'error')
            return redirect(url_for('student_courses'))
        
        assignment = session.get(CourseAssignment, assignment_id)
        if not assignment or assignment.lesson_id != lesson_id:
            flash('Задание не найдено', 'error')
            return redirect(url_for('student_lesson_view', lesson_id=lesson_id))
        
        # Проверяем, есть ли уже ответ
        existing_submission = session.query(CourseSubmission)\
            .filter_by(assignment_id=assignment_id, enrollment_id=enrollment.id)\
            .first()
        
        if existing_submission:
            if existing_submission.is_approved():
                flash('Это задание уже одобрено. Изменения невозможны.', 'info')
            elif existing_submission.status == 'submitted':
                # Обновляем неproверенный ответ
                existing_submission.content = content
                existing_submission.submitted_at = datetime.now()
                flash('Ответ обновлен и отправлен на проверку', 'success')
            elif existing_submission.is_rejected():
                # Переотправляем отклоненное задание
                existing_submission.content = content
                existing_submission.status = 'submitted'
                existing_submission.is_checked = False
                existing_submission.submitted_at = datetime.now()
                existing_submission.checked_at = None
                flash('Исправленный ответ отправлен на повторную проверку', 'success')
        else:
            # Создаем новый ответ
            submission = CourseSubmission(
                assignment_id=assignment_id,
                enrollment_id=enrollment.id,
                content=content,
                status='submitted'
            )
            session.add(submission)
            flash('Ответ отправлен на проверку', 'success')
        
        session.commit()
        return redirect(url_for('student_lesson_view', lesson_id=lesson_id))

@app.route('/student/lessons/<int:lesson_id>/complete', methods=['POST'])
@role_required('student')
def student_complete_lesson(lesson_id):
    """Завершение урока студентом (только если нет заданий или все проверены)"""
    with session_scope() as session:
        student_id = flask_session.get('student_id')
        
        lesson = session.get(CourseLesson, lesson_id)
        enrollment = session.query(CourseEnrollment)\
            .filter_by(course_id=lesson.module.course_id, student_id=student_id, is_active=True)\
            .first()
        
        if not enrollment or not enrollment.can_access_lesson(lesson_id):
            flash('У вас нет доступа к этому уроку', 'error')
            return redirect(url_for('student_courses'))
        
        # Проверяем, можно ли завершить урок
        assignments = session.query(CourseAssignment)\
            .filter_by(lesson_id=lesson_id)\
            .all()
        
        if assignments:
            # Если есть задания, проверяем их выполнение
            for assignment in assignments:
                submission = session.query(CourseSubmission)\
                    .filter_by(assignment_id=assignment.id, enrollment_id=enrollment.id)\
                    .first()
                if not submission or not submission.is_approved():
                    flash('Сначала выполните и получите одобрение всех заданий урока', 'warning')
                    return redirect(url_for('student_lesson_view', lesson_id=lesson_id))
        
        # Отмечаем урок как завершенный
        enrollment.mark_lesson_completed(lesson_id)
        session.commit()
        
        flash('Урок завершен! Открыт доступ к следующему уроку.', 'success')
        return redirect(url_for('student_course_detail', course_id=lesson.module.course_id))

# ==================== ПРОВЕРКА ЗАДАНИЙ РЕПЕТИТОРОМ ====================

@app.route('/tutor/submissions')
@role_required('tutor')
def tutor_submissions():
    """Список ответов студентов на проверку"""
    with session_scope() as session:
        user_id = flask_session.get('user_id')
        
        # Получаем все непроверенные ответы студентов репетитора
        submissions = session.query(CourseSubmission)\
            .join(CourseEnrollment)\
            .join(Course)\
            .join(CourseAssignment)\
            .join(CourseLesson)\
            .filter(Course.tutor_id == user_id)\
            .filter(CourseSubmission.is_checked == False)\
            .order_by(CourseSubmission.submitted_at.desc())\
            .all()
        
        return render_template('tutor_submissions.html', submissions=submissions)

@app.route('/tutor/submissions/<int:submission_id>/check', methods=['GET', 'POST'])
@role_required('tutor')
def check_submission(submission_id):
    """Проверка ответа студента"""
    with session_scope() as session:
        user_id = flask_session.get('user_id')
        
        submission = session.get(CourseSubmission, submission_id)
        if not submission:
            flash('Ответ не найден', 'error')
            return redirect(url_for('tutor_submissions'))
        
        # Проверяем, принадлежит ли курс репетитору
        course = submission.assignment.lesson.module.course
        if course.tutor_id != user_id:
            flash('У вас нет доступа к этому ответу', 'error')
            return redirect(url_for('tutor_submissions'))
        
        if request.method == 'POST':
            action = request.form.get('action')  # 'approve' или 'reject'
            points = request.form.get('points')
            feedback = request.form.get('feedback', '').strip()
            
            try:
                points = int(points) if points else None
            except ValueError:
                points = None
            
            if action == 'approve':
                # Одобряем задание
                submission.is_checked = True
                submission.status = 'approved'
                submission.points = points
                submission.tutor_feedback = feedback
                submission.checked_at = datetime.now()
                
                # Проверяем, можно ли открыть следующий урок
                enrollment = submission.enrollment
                lesson = submission.assignment.lesson
                
                # Проверяем, все ли задания урока одобрены
                lesson_assignments = session.query(CourseAssignment)\
                    .filter_by(lesson_id=lesson.id)\
                    .all()
                
                all_approved = True
                for assignment in lesson_assignments:
                    assignment_submission = session.query(CourseSubmission)\
                        .filter_by(assignment_id=assignment.id, enrollment_id=enrollment.id)\
                        .first()
                    if not assignment_submission or not assignment_submission.is_approved():
                        all_approved = False
                        break
                
                # Если все задания урока одобрены, студент может завершить урок
                if all_approved and lesson.id == enrollment.current_lesson_id:
                    # Автоматически завершаем урок
                    enrollment.mark_lesson_completed(lesson.id)
                
                session.commit()
                flash('Задание одобрено!', 'success')
                
            elif action == 'reject':
                # Отклоняем задание
                submission.is_checked = True
                submission.status = 'rejected'
                submission.points = 0  # При отклонении баллы = 0
                submission.tutor_feedback = feedback
                submission.checked_at = datetime.now()
                
                session.commit()
                flash('Задание отклонено. Студент сможет отправить исправленный вариант.', 'warning')
            
            return redirect(url_for('tutor_submissions'))
        
        return render_template('check_submission.html', submission=submission)

# ==================== АНАЛИТИКА ПРОГРЕССА ====================

@app.route('/analytics')
@role_required('admin', 'tutor')
def analytics_dashboard():
    """Главная страница аналитики"""
    with session_scope() as session:
        user_role = flask_session.get('role')
        user_id = flask_session.get('user_id')
        
        # Базовая статистика
        stats = {}
        
        if user_role == 'admin':
            # Статистика для администратора
            stats['total_courses'] = session.query(Course).count()
            stats['total_students'] = session.query(Student).count()
            stats['total_tutors'] = session.query(User).filter_by(role='tutor').count()
            stats['total_enrollments'] = session.query(CourseEnrollment).filter_by(is_active=True).count()
            
            # Топ курсы по количеству студентов
            popular_courses = session.query(Course, func.count(CourseEnrollment.id).label('enrollment_count'))\
                .join(CourseEnrollment)\
                .filter(CourseEnrollment.is_active == True)\
                .group_by(Course.id)\
                .order_by(func.count(CourseEnrollment.id).desc())\
                .limit(10)\
                .all()
            
        else:  # tutor
            # Статистика для репетитора
            stats['total_courses'] = session.query(Course).filter_by(tutor_id=user_id).count()
            stats['total_students'] = session.query(Student).filter_by(tutor_id=user_id).count()
            stats['total_enrollments'] = session.query(CourseEnrollment)\
                .join(Course)\
                .filter(Course.tutor_id == user_id, CourseEnrollment.is_active == True)\
                .count()
            
            # Курсы репетитора
            popular_courses = session.query(Course, func.count(CourseEnrollment.id).label('enrollment_count'))\
                .join(CourseEnrollment)\
                .filter(Course.tutor_id == user_id, CourseEnrollment.is_active == True)\
                .group_by(Course.id)\
                .order_by(func.count(CourseEnrollment.id).desc())\
                .all()
        
        # Общая статистика по заданиям
        stats['pending_submissions'] = session.query(CourseSubmission)\
            .filter_by(is_checked=False)\
            .count()
        
        stats['approved_submissions'] = session.query(CourseSubmission)\
            .filter_by(status='approved')\
            .count()
        
        stats['rejected_submissions'] = session.query(CourseSubmission)\
            .filter_by(status='rejected')\
            .count()
        
        return render_template('analytics_dashboard.html', 
                             stats=stats, 
                             popular_courses=popular_courses)

@app.route('/analytics/students')
@role_required('admin', 'tutor')
def student_analytics():
    """Аналитика по студентам"""
    with session_scope() as session:
        user_role = flask_session.get('role')
        user_id = flask_session.get('user_id')
        
        # Базовый запрос студентов
        if user_role == 'admin':
            students_query = session.query(Student)
        else:
            students_query = session.query(Student).filter_by(tutor_id=user_id)
        
        students = students_query.all()
        
        # Аналитика для каждого студента
        student_analytics = []
        for student in students:
            enrollments = session.query(CourseEnrollment)\
                .filter_by(student_id=student.id, is_active=True)\
                .all()
            
            total_courses = len(enrollments)
            completed_courses = sum(1 for e in enrollments if e.progress_percentage >= 100)
            in_progress_courses = sum(1 for e in enrollments if 0 < e.progress_percentage < 100)
            avg_progress = sum(e.progress_percentage for e in enrollments) / total_courses if total_courses > 0 else 0
            
            # Статистика по заданиям
            total_submissions = session.query(CourseSubmission)\
                .join(CourseEnrollment)\
                .filter(CourseEnrollment.student_id == student.id)\
                .count()
            
            approved_submissions = session.query(CourseSubmission)\
                .join(CourseEnrollment)\
                .filter(CourseEnrollment.student_id == student.id)\
                .filter(CourseSubmission.status == 'approved')\
                .count()
            
            rejected_submissions = session.query(CourseSubmission)\
                .join(CourseEnrollment)\
                .filter(CourseEnrollment.student_id == student.id)\
                .filter(CourseSubmission.status == 'rejected')\
                .count()
            
            student_analytics.append({
                'student': student,
                'total_courses': total_courses,
                'completed_courses': completed_courses,
                'in_progress_courses': in_progress_courses,
                'avg_progress': avg_progress,
                'total_submissions': total_submissions,
                'approved_submissions': approved_submissions,
                'rejected_submissions': rejected_submissions,
                'success_rate': (approved_submissions / total_submissions * 100) if total_submissions > 0 else 0
            })
        
        # Сортируем по среднему прогрессу
        student_analytics.sort(key=lambda x: x['avg_progress'], reverse=True)
        
        return render_template('student_analytics.html', student_analytics=student_analytics)

@app.route('/analytics/courses')
@role_required('admin', 'tutor')
def course_analytics():
    """Аналитика по курсам"""
    with session_scope() as session:
        user_role = flask_session.get('role')
        user_id = flask_session.get('user_id')
        
        # Базовый запрос курсов
        if user_role == 'admin':
            courses_query = session.query(Course)
        else:
            courses_query = session.query(Course).filter_by(tutor_id=user_id)
        
        courses = courses_query.all()
        
        # Аналитика для каждого курса
        course_analytics = []
        for course in courses:
            enrollments = session.query(CourseEnrollment)\
                .filter_by(course_id=course.id, is_active=True)\
                .all()
            
            total_students = len(enrollments)
            completed_students = sum(1 for e in enrollments if e.progress_percentage >= 100)
            avg_progress = sum(e.progress_percentage for e in enrollments) / total_students if total_students > 0 else 0
            
            # Количество уроков в курсе
            total_lessons = session.query(CourseLesson)\
                .join(CourseModule)\
                .filter(CourseModule.course_id == course.id)\
                .count()
            
            # Статистика по заданиям
            total_assignments = session.query(CourseAssignment)\
                .join(CourseLesson)\
                .join(CourseModule)\
                .filter(CourseModule.course_id == course.id)\
                .count()
            
            total_submissions = session.query(CourseSubmission)\
                .join(CourseEnrollment)\
                .filter(CourseEnrollment.course_id == course.id)\
                .count()
            
            course_analytics.append({
                'course': course,
                'total_students': total_students,
                'completed_students': completed_students,
                'completion_rate': (completed_students / total_students * 100) if total_students > 0 else 0,
                'avg_progress': avg_progress,
                'total_lessons': total_lessons,
                'total_assignments': total_assignments,
                'total_submissions': total_submissions
            })
        
        # Сортируем по проценту завершения
        course_analytics.sort(key=lambda x: x['completion_rate'], reverse=True)
        
        return render_template('course_analytics.html', course_analytics=course_analytics)

# ==================== УПРАВЛЕНИЕ РАЗРЕШЕНИЯМИ НА КУРСЫ ====================

@app.route('/users/toggle_course_permission/<int:user_id>', methods=['POST'])
@role_required('admin')
def toggle_course_permission(user_id):
    """Переключает разрешение на создание курсов"""
    with session_scope() as session:
        user = session.get(User, user_id)
        if not user:
            flash('Пользователь не найден', 'error')
            return redirect(url_for('manage_users'))
        
        if user.role != 'tutor':
            flash('Разрешения на курсы можно выдавать только репетиторам', 'error')
            return redirect(url_for('manage_users'))
        
        user.can_create_courses = not user.can_create_courses
        session.commit()
        
        status = "выдано" if user.can_create_courses else "отозвано"
        flash(f'Разрешение на создание курсов {status} для {user.username}', 'success')
        
        return redirect(url_for('manage_users'))

@app.route('/analytics/student/<int:student_id>')
@role_required('admin', 'tutor')
def detailed_student_analytics(student_id):
    """Детальная аналитика по студенту"""
    with session_scope() as session:
        user_role = flask_session.get('role')
        user_id = flask_session.get('user_id')
        
        student = session.get(Student, student_id)
        if not student:
            flash('Студент не найден', 'error')
            return redirect(url_for('student_analytics'))
        
        # Проверяем доступ
        if user_role == 'tutor' and student.tutor_id != user_id:
            flash('У вас нет доступа к этому студенту', 'error')
            return redirect(url_for('student_analytics'))
        
        # Получаем записи на курсы
        enrollments = session.query(CourseEnrollment)\
            .filter_by(student_id=student_id, is_active=True)\
            .join(Course)\
            .order_by(Course.title)\
            .all()
        
        # Детальная информация по каждому курсу
        course_details = []
        for enrollment in enrollments:
            course = enrollment.course
            
            # Уроки курса
            modules = session.query(CourseModule)\
                .filter_by(course_id=course.id)\
                .order_by(CourseModule.order_index)\
                .all()
            
            lessons_completed = 0
            lessons_total = 0
            lessons_details = []
            
            for module in modules:
                lessons = session.query(CourseLesson)\
                    .filter_by(module_id=module.id)\
                    .order_by(CourseLesson.order_index)\
                    .all()
                
                for lesson in lessons:
                    lessons_total += 1
                    is_completed = lesson.id in enrollment.get_completed_lesson_ids()
                    if is_completed:
                        lessons_completed += 1
                    
                    # Задания урока
                    assignments = session.query(CourseAssignment)\
                        .filter_by(lesson_id=lesson.id)\
                        .all()
                    
                    assignment_stats = []
                    for assignment in assignments:
                        submission = session.query(CourseSubmission)\
                            .filter_by(assignment_id=assignment.id, enrollment_id=enrollment.id)\
                            .first()
                        
                        assignment_stats.append({
                            'assignment': assignment,
                            'submission': submission,
                            'status': submission.status if submission else 'not_submitted'
                        })
                    
                    lessons_details.append({
                        'module': module,
                        'lesson': lesson,
                        'is_completed': is_completed,
                        'is_current': lesson.id == enrollment.current_lesson_id,
                        'assignments': assignment_stats
                    })
            
            course_details.append({
                'enrollment': enrollment,
                'course': course,
                'lessons_completed': lessons_completed,
                'lessons_total': lessons_total,
                'lessons_details': lessons_details
            })
        
        return render_template('detailed_student_analytics.html', 
                             student=student, 
                             course_details=course_details)

# ==================== РЕЗЕРВНОЕ КОПИРОВАНИЕ И ЭКСПОРТ ====================

@app.route('/backup')
@role_required('admin')
def backup_dashboard():
    """Панель резервного копирования"""
    import os
    import glob
    from datetime import datetime
    
    # Папка для бэкапов
    backup_dir = 'backups'
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
    
    # Список существующих бэкапов
    backup_files = []
    for filepath in glob.glob(os.path.join(backup_dir, '*.db')):
        filename = os.path.basename(filepath)
        file_size = os.path.getsize(filepath)
        file_date = datetime.fromtimestamp(os.path.getmtime(filepath))
        backup_files.append({
            'filename': filename,
            'filepath': filepath,
            'size': file_size,
            'date': file_date
        })
    
    backup_files.sort(key=lambda x: x['date'], reverse=True)
    
    return render_template('backup_dashboard.html', backup_files=backup_files)

@app.route('/backup/create', methods=['POST'])
@role_required('admin')
def create_backup():
    """Создание резервной копии"""
    import shutil
    import os
    from datetime import datetime
    
    try:
        backup_dir = 'backups'
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        
        # Имя файла бэкапа
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f'backup_{timestamp}.db'
        backup_path = os.path.join(backup_dir, backup_filename)
        
        # Копируем файл базы данных
        shutil.copy2(config.DB_NAME, backup_path)
        
        flash(f'Резервная копия создана: {backup_filename}', 'success')
    except Exception as e:
        flash(f'Ошибка создания резервной копии: {e}', 'error')
    
    return redirect(url_for('backup_dashboard'))

@app.route('/backup/restore/<filename>', methods=['POST'])
@role_required('admin')
def restore_backup(filename):
    """Восстановление из резервной копии"""
    import shutil
    import os
    
    try:
        backup_path = os.path.join('backups', filename)
        if not os.path.exists(backup_path):
            flash('Файл резервной копии не найден', 'error')
            return redirect(url_for('backup_dashboard'))
        
        # Создаем копию текущей БД
        current_backup = f"{config.DB_NAME}.before_restore"
        shutil.copy2(config.DB_NAME, current_backup)
        
        # Восстанавливаем из бэкапа
        shutil.copy2(backup_path, config.DB_NAME)
        
        flash(f'База данных восстановлена из {filename}. Создана копия текущей БД: {current_backup}', 'success')
    except Exception as e:
        flash(f'Ошибка восстановления: {e}', 'error')
    
    return redirect(url_for('backup_dashboard'))

@app.route('/export/students')
@role_required('admin', 'tutor')
def export_students():
    """Экспорт данных студентов в CSV"""
    import csv
    import io
    from flask import Response
    
    with session_scope() as session:
        user_role = flask_session.get('role')
        user_id = flask_session.get('user_id')
        
        # Фильтруем студентов
        if user_role == 'admin':
            students = session.query(Student).all()
        else:
            students = session.query(Student).filter_by(tutor_id=user_id).all()
        
        # Создаем CSV
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Заголовки
        writer.writerow(['ID', 'ФИО', 'Email', 'Телефон', 'Репетитор', 'Активен', 'Дата создания'])
        
        # Данные
        for student in students:
            tutor_name = student.tutor.username if student.tutor else 'Не назначен'
            writer.writerow([
                student.id,
                student.full_name,
                student.email,
                student.phone_number,
                tutor_name,
                'Да' if student.is_active else 'Нет',
                student.created_at.strftime('%d.%m.%Y %H:%M') if student.created_at else ''
            ])
        
        output.seek(0)
        
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=students.csv'}
        )

@app.route('/export/courses')
@role_required('admin', 'tutor')
def export_courses():
    """Экспорт данных курсов в CSV"""
    import csv
    import io
    from flask import Response
    
    with session_scope() as session:
        user_role = flask_session.get('role')
        user_id = flask_session.get('user_id')
        
        # Фильтруем курсы
        if user_role == 'admin':
            courses = session.query(Course).all()
        else:
            courses = session.query(Course).filter_by(tutor_id=user_id).all()
        
        # Создаем CSV
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Заголовки
        writer.writerow(['ID', 'Название', 'Описание', 'Репетитор', 'Студентов', 'Средний прогресс', 'Создан'])
        
        # Данные
        for course in courses:
            enrollments = session.query(CourseEnrollment)\
                .filter_by(course_id=course.id, is_active=True)\
                .all()
            
            total_students = len(enrollments)
            avg_progress = sum(e.progress_percentage for e in enrollments) / total_students if total_students > 0 else 0
            
            writer.writerow([
                course.id,
                course.title,
                course.description,
                course.tutor.username,
                total_students,
                f"{avg_progress:.1f}%",
                course.created_at.strftime('%d.%m.%Y') if course.created_at else ''
            ])
        
        output.seek(0)
        
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=courses.csv'}
        )

@app.route('/')
def index():
    if flask_session.get('role') == 'student':
        return redirect(url_for('student_dashboard'))
    else:
        return redirect(url_for('today_lessons'))

@app.route('/add_student', methods=['GET', 'POST'])
@role_required('admin', 'tutor')
def add_student():
    current_user_info = get_current_user_info()
    
    if request.method == 'POST':
        # Валидация данных
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        
        if not email:
            flash('Email обязателен для создания аккаунта студента', 'error')
            return redirect(url_for('add_student'))
        
        if len(password) < 6:
            flash('Пароль должен содержать минимум 6 символов', 'error')
            return redirect(url_for('add_student'))
        
        with session_scope() as session:
            # Проверяем, не существует ли уже пользователь с таким email
            existing_user = session.query(User).filter_by(email=email).first()
            if existing_user:
                flash('Пользователь с таким email уже существует', 'error')
                return redirect(url_for('add_student'))
            
            # Определяем репетитора
            if current_user_info and current_user_info['role'] == 'tutor':
                tutor_id = current_user_info['id']
            else:  # Администратор может выбрать репетитора
                tutor_id = request.form.get('tutor_id')
                if tutor_id:
                    tutor_id = int(tutor_id)
                else:
                    tutor_id = None
            
            # Создаем студента
            student = Student(
                full_name=request.form['full_name'],
                lessons_count=int(request.form['lessons_count']),
                telegram_chat_id=request.form['telegram_chat_id'] or None,
                receive_notifications=True,
                tutor_id=tutor_id
            )
            session.add(student)
            session.flush()  # Получаем ID студента
            
            # Создаем аккаунт для студента
            user_account = User(
                username=email,  # Используем email как логин
                email=email,
                role='student',
                is_approved=True,
                student_id=student.id
            )
            user_account.set_password(password)
            session.add(user_account)
            session.commit()
            
            # Сообщение об успехе
            if tutor_id:
                tutor = session.get(User, tutor_id)
                flash(f'Студент {student.full_name} добавлен с аккаунтом {email}! Привязан к репетитору {tutor.username}.', 'success')
            else:
                flash(f'Студент {student.full_name} добавлен с аккаунтом {email}!', 'success')
            
            return redirect(url_for('all_students'))
    
    # Для формы получаем список репетиторов (если пользователь - администратор)
    tutors = []
    if current_user_info and current_user_info['role'] == 'admin':
        with session_scope() as session:
            tutors = session.query(User).filter_by(role='tutor', is_approved=True).all()
    
    return render_template('add_student.html', tutors=tutors, current_user=current_user_info)

@app.route('/all_students')
@role_required('admin', 'tutor')
def all_students():
    search_query = request.args.get('search', '').strip()
    show_archived = request.args.get('archived') == 'true'
    current_user_info = get_current_user_info()
    
    with session_scope() as session:
        query = session.query(Student)
        
        # Фильтрация по репетитору
        query = filter_students_by_tutor(query, session)
        
        if show_archived:
            query = query.filter_by(is_archived=True)
        else:
            query = query.filter_by(is_archived=False)
        
        if search_query:
            query = query.filter(
                or_(
                    Student.full_name.ilike(f'%{search_query}%'),
                    Student.telegram_chat_id.ilike(f'%{search_query}%')
                )
            )
        
        students = query.order_by(Student.full_name).all()
        
        # Получаем статистику по урокам для каждого студента
        for student in students:
            # Всего уроков
            total_lessons = session.query(Lesson).filter_by(student_id=student.id).count()
            # Проведенные уроки
            completed_lessons = session.query(Lesson).filter_by(
                student_id=student.id, 
                status='проведен'
            ).count()
            # Запланированные уроки (в будущем)
            scheduled_lessons = session.query(Lesson).filter(
                Lesson.student_id == student.id,
                Lesson.date_time > datetime.now(),
                Lesson.status == 'запланирован'
            ).count()
            
            student.total_lessons_count = total_lessons
            student.completed_lessons_count = completed_lessons
            student.scheduled_lessons_count = scheduled_lessons
        
        return render_template('all_students.html', 
                               students=students, 
                               search_query=search_query,
                               show_archived=show_archived,
                               current_user=current_user_info)

@app.route('/today_lessons')
@role_required('admin', 'tutor')
def today_lessons():
    with session_scope() as session:
        # Получаем уроки на сегодня
        today = datetime.now().date()
        lessons = session.query(Lesson).filter(
            func.date(Lesson.date_time) == today
        ).order_by(Lesson.date_time).all()
        
        return render_template('today_lessons.html', lessons=lessons)

@app.route('/all_lessons')
@role_required('admin', 'tutor')  
def all_lessons():
    page = request.args.get('page', 1, type=int)
    per_page = 20  # Количество уроков на страницу
    
    search_query = request.args.get('search', '').strip()
    status_filter = request.args.get('status', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    
    with session_scope() as session:
        query = session.query(Lesson).join(Student)
        
        # Применяем фильтры
        if search_query:
            query = query.filter(Student.full_name.ilike(f'%{search_query}%'))
        
        if status_filter:
            query = query.filter(Lesson.status == status_filter)
        
        if date_from:
            try:
                date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
                query = query.filter(Lesson.date_time >= date_from_obj)
            except ValueError:
                pass
        
        if date_to:
            try:
                date_to_obj = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
                query = query.filter(Lesson.date_time < date_to_obj)
            except ValueError:
                pass
        
        # Сортировка по дате (новые сначала)
        query = query.order_by(Lesson.date_time.desc())
        
        # Пагинация
        total = query.count()
        lessons = query.offset((page - 1) * per_page).limit(per_page).all()
        
        # Информация о пагинации
        pagination = {
            'page': page,
            'per_page': per_page,
            'total': total,
            'pages': (total + per_page - 1) // per_page,
            'has_prev': page > 1,
            'has_next': page * per_page < total,
            'prev_num': page - 1 if page > 1 else None,
            'next_num': page + 1 if page * per_page < total else None
        }
        
        return render_template('all_lessons.html', 
                               lessons=lessons, 
                               pagination=pagination,
                               search_query=search_query,
                               status_filter=status_filter,
                               date_from=date_from,
                               date_to=date_to)

@app.route('/add_lesson', methods=['GET', 'POST'])
@role_required('admin', 'tutor')
def add_lesson():
    if request.method == 'POST':
        with session_scope() as session:
            lesson = Lesson(
                student_id=int(request.form['student_id']),
                date_time=datetime.strptime(request.form['date_time'], '%Y-%m-%dT%H:%M'),
                status='запланирован'
            )
            session.add(lesson)
            session.flush()
            
            # Отправляем уведомление студенту
            student = session.query(Student).get(lesson.student_id)
            if student and student.telegram_chat_id and student.receive_notifications:
                from main_tg import send_notification
                lesson_time = lesson.date_time.strftime('%d.%m.%Y в %H:%M')
                send_notification(
                    student.telegram_chat_id,
                    f"📚 Запланировано новое занятие!\n\n"
                    f"Дата и время: {lesson_time}\n"
                    f"Не забудьте подготовиться!"
                )
            
            # Уведомляем родителей
            parents = session.query(Parent).filter_by(student_id=student.id).all()
            for parent in parents:
                from main_tg import send_notification
                lesson_time = lesson.date_time.strftime('%d.%m.%Y в %H:%M')
                send_notification(
                    parent.telegram_chat_id,
                    f"📚 Запланировано занятие для {student.full_name}\n\n"
                    f"Дата и время: {lesson_time}"
                )
            
            flash('Урок добавлен!', 'success')
            return redirect(url_for('all_lessons'))
    
    # Получаем список студентов для формы
    with session_scope() as session:
        students = session.query(Student).filter_by(is_archived=False).order_by(Student.full_name).all()
        return render_template('add_lesson.html', students=students)

@app.route('/student_dashboard')
@role_required('student')
def student_dashboard():
    student_id = flask_session.get('student_id')
    with session_scope() as session:
        lessons = session.query(Lesson).filter_by(student_id=student_id).order_by(Lesson.date_time.desc()).all()
        return render_template('student_dashboard.html', lessons=lessons)

@app.route('/student_homework')
@role_required('student')
def student_homework():
    student_id = flask_session.get('student_id')
    with session_scope() as session:
        homeworks = session.query(Homework).filter_by(student_id=student_id).order_by(Homework.due_date.asc()).all()
        return render_template('student_homework.html', homeworks=homeworks)

@app.route('/submit_homework_student/<int:homework_id>', methods=['POST'])
@role_required('student')
def submit_homework_student(homework_id):
    student_id = flask_session.get('student_id')
    with session_scope() as session:
        homework = session.query(Homework).filter_by(id=homework_id, student_id=student_id).first()
        if homework and not homework.submitted_date:
            homework.student_comment = request.form.get('student_comment', '').strip()
            homework.submitted_date = datetime.now()
            homework.is_completed = True  # Отмечаем как выполненное студентом
            
            # Уведомляем репетитора
            comment_text = f"\n\nКомментарий: {homework.student_comment}" if homework.student_comment else ""
            from main_tg import send_notification
            send_notification(config.TUTOR_ID, 
                f"📤 Студент {homework.student.full_name} отправил на проверку домашнее задание:\n"
                f"'{homework.description}'{comment_text}\n\n"
                f"Подтвердите выполнение в системе.")
            
            flash('Домашнее задание отправлено на проверку!', 'success')
        else:
            flash('Домашнее задание уже отправлено или не найдено', 'error')
    
    return redirect(url_for('student_homework'))

# =============== ДОПОЛНИТЕЛЬНЫЕ МАРШРУТЫ ===============

@app.route('/view_student_card/<int:student_id>')
@role_required('admin', 'tutor')
def view_student_card(student_id):
    with session_scope() as session:
        student = session.get(Student, student_id)
        if not student:
            flash('Студент не найден', 'error')
            return redirect(url_for('all_students'))
        
        # Получаем последние уроки
        recent_lessons = session.query(Lesson).filter_by(student_id=student_id).order_by(Lesson.date_time.desc()).limit(10).all()
        
        # Получаем домашние задания
        homeworks = session.query(Homework).filter_by(student_id=student_id).order_by(Homework.due_date.desc()).all()
        
        # Получаем платежи
        payments = session.query(Payment).filter_by(student_id=student_id).order_by(Payment.payment_date.desc()).limit(5).all()
        
        # Получаем родителей
        parents = session.query(Parent).filter_by(student_id=student_id).all()
        
        return render_template('student_card.html', 
                               student=student, 
                               recent_lessons=recent_lessons,
                               homeworks=homeworks,
                               payments=payments,
                               parents=parents)

@app.route('/edit_student/<int:student_id>', methods=['GET', 'POST'])
@role_required('admin', 'tutor')
def edit_student(student_id):
    with session_scope() as session:
        student = session.get(Student, student_id)
        if not student:
            flash('Студент не найден', 'error')
            return redirect(url_for('all_students'))
        
        if request.method == 'POST':
            student.full_name = request.form['full_name']
            student.lessons_count = int(request.form['lessons_count'])
            student.telegram_chat_id = request.form['telegram_chat_id']
            student.receive_notifications = 'receive_notifications' in request.form
            
            session.commit()
            flash('Данные студента обновлены!', 'success')
            return redirect(url_for('view_student_card', student_id=student_id))
        
        return render_template('edit_student.html', student=student)

@app.route('/archive_student/<int:student_id>')
@role_required('admin', 'tutor')
def archive_student(student_id):
    with session_scope() as session:
        student = session.get(Student, student_id)
        if student:
            student.is_archived = True
            session.commit()
            flash(f'Студент {student.full_name} архивирован', 'success')
        else:
            flash('Студент не найден', 'error')
    return redirect(url_for('all_students'))

@app.route('/restore_student/<int:student_id>')
@role_required('admin', 'tutor')
def restore_student(student_id):
    with session_scope() as session:
        student = session.get(Student, student_id)
        if student:
            student.is_archived = False
            session.commit()
            flash(f'Студент {student.full_name} восстановлен', 'success')
        else:
            flash('Студент не найден', 'error')
    return redirect(url_for('all_students', archived='true'))

@app.route('/edit_lesson/<int:lesson_id>', methods=['GET', 'POST'])
@role_required('admin', 'tutor')
def edit_lesson(lesson_id):
    with session_scope() as session:
        lesson = session.get(Lesson, lesson_id)
        if not lesson:
            flash('Урок не найден', 'error')
            return redirect(url_for('all_lessons'))
        
        if request.method == 'POST':
            lesson.date_time = datetime.strptime(request.form['date_time'], '%Y-%m-%dT%H:%M')
            lesson.status = request.form['status']
            lesson.topic_covered = request.form.get('topic_covered', '').strip()
            lesson.video_link = request.form.get('video_link', '').strip()
            lesson.video_status = request.form.get('video_status', 'pending')
            
            next_lesson_str = request.form.get('next_lesson_date', '').strip()
            if next_lesson_str:
                try:
                    lesson.next_lesson_date = datetime.strptime(next_lesson_str, '%Y-%m-%dT%H:%M')
                except ValueError:
                    lesson.next_lesson_date = None
            else:
                lesson.next_lesson_date = None
            
            session.commit()
            flash('Урок обновлен!', 'success')
            return redirect(url_for('all_lessons'))
        
        students = session.query(Student).filter_by(is_archived=False).order_by(Student.full_name).all()
        return render_template('edit_lesson.html', lesson=lesson, students=students)

@app.route('/delete_lesson/<int:lesson_id>')
@role_required('admin', 'tutor')
def delete_lesson(lesson_id):
    with session_scope() as session:
        lesson = session.get(Lesson, lesson_id)
        if lesson:
            student_name = lesson.student.full_name
            session.delete(lesson)
            session.commit()
            flash(f'Урок студента {student_name} удален', 'success')
        else:
            flash('Урок не найден', 'error')
    return redirect(url_for('all_lessons'))

@app.route('/add_homework/<int:student_id>', methods=['GET', 'POST'])
@role_required('admin', 'tutor')
def add_homework(student_id):
    with session_scope() as session:
        student = session.get(Student, student_id)
        if not student:
            flash('Студент не найден', 'error')
            return redirect(url_for('all_students'))
        
        if request.method == 'POST':
            homework = Homework(
                student_id=student_id,
                description=request.form['description'],
                due_date=datetime.strptime(request.form['due_date'], '%Y-%m-%d') if request.form['due_date'] else None
            )
            session.add(homework)
            session.commit()
            
            # Уведомляем студента
            if student.telegram_chat_id and student.receive_notifications:
                from main_tg import send_notification
                due_text = f" до {homework.due_date.strftime('%d.%m.%Y')}" if homework.due_date else ""
                send_notification(
                    student.telegram_chat_id,
                    f"📝 Новое домашнее задание{due_text}:\n\n{homework.description}"
                )
            
            flash('Домашнее задание добавлено!', 'success')
            return redirect(url_for('view_student_card', student_id=student_id))
        
        return render_template('add_homework.html', student=student)

@app.route('/pending_homeworks')
@role_required('admin', 'tutor')
def pending_homeworks():
    with session_scope() as session:
        pending_homeworks = session.query(Homework).filter(
            Homework.submitted_date.isnot(None),
            Homework.is_confirmed_by_tutor == False
        ).order_by(Homework.submitted_date.desc()).all()
        
        return render_template('pending_homeworks.html', pending_homeworks=pending_homeworks)

@app.route('/confirm_homework/<int:homework_id>')
@role_required('admin', 'tutor')
def confirm_homework(homework_id):
    with session_scope() as session:
        homework = session.get(Homework, homework_id)
        if homework and homework.submitted_date and not homework.is_confirmed_by_tutor:
            homework.is_confirmed_by_tutor = True
            session.commit()
            
            # Уведомляем студента
            student = homework.student
            if student.telegram_chat_id and student.receive_notifications:
                from main_tg import send_notification
                send_notification(
                    student.telegram_chat_id,
                    f"✅ Ваше домашнее задание проверено и принято!\n\n"
                    f"Задание: {homework.description}"
                )
            
            flash('Домашнее задание подтверждено!', 'success')
        else:
            flash('Ошибка подтверждения домашнего задания', 'error')
    
    return redirect(url_for('pending_homeworks'))

@app.route('/statistics')
@role_required('admin', 'tutor')
def statistics():
    with session_scope() as session:
        # Общая статистика
        total_students = session.query(Student).filter_by(is_archived=False).count()
        total_lessons = session.query(Lesson).count()
        completed_lessons = session.query(Lesson).filter_by(status='проведен').count()
        pending_homeworks = session.query(Homework).filter(
            Homework.submitted_date.isnot(None),
            Homework.is_confirmed_by_tutor == False
        ).count()
        
        # Статистика по месяцам
        from sqlalchemy import extract
        current_month_lessons = session.query(Lesson).filter(
            extract('month', Lesson.date_time) == datetime.now().month,
            extract('year', Lesson.date_time) == datetime.now().year
        ).count()
        
        stats = {
            'total_students': total_students,
            'total_lessons': total_lessons,
            'completed_lessons': completed_lessons,
            'pending_homeworks': pending_homeworks,
            'current_month_lessons': current_month_lessons,
            'completion_rate': round(completed_lessons / total_lessons * 100, 1) if total_lessons > 0 else 0
        }
        
        return render_template('statistics.html', stats=stats)

@app.route('/manage_users')
@role_required('admin')
def manage_users():
    with session_scope() as session:
        users = session.query(User).all()
        return render_template('manage_users.html', users=users)

@app.route('/create_user', methods=['GET', 'POST'])
@role_required('admin')
def create_user():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        role = request.form['role']
        student_id = request.form.get('student_id') if role == 'student' else None
        
        with session_scope() as session:
            # Проверяем уникальность
            if session.query(User).filter_by(username=username).first():
                flash('Пользователь с таким логином уже существует', 'error')
                return render_template('create_user.html')
            
            if session.query(User).filter_by(email=email).first():
                flash('Пользователь с таким email уже существует', 'error')
                return render_template('create_user.html')
            
            user = User(username=username, email=email, role=role)
            user.set_password(password)
            user.is_approved = True  # Администратор создает уже одобренных пользователей
            
            if role == 'student' and student_id:
                user.student_id = int(student_id)
            
            session.add(user)
            session.commit()
            
            flash('Пользователь создан!', 'success')
            return redirect(url_for('manage_users'))
    
    # Получаем список студентов без аккаунтов
    with session_scope() as session:
        # Получаем ID студентов, у которых есть аккаунты
        student_ids_with_accounts = session.query(User.student_id).filter(User.student_id.isnot(None)).all()
        student_ids_with_accounts = [id[0] for id in student_ids_with_accounts]
        
        # Получаем студентов без аккаунтов
        students_without_accounts = session.query(Student).filter(
            ~Student.id.in_(student_ids_with_accounts)
        ).all()
        
        return render_template('create_user.html', students=students_without_accounts)

@app.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
@role_required('admin')
def edit_user(user_id):
    with session_scope() as session:
        user = session.get(User, user_id)
        if not user:
            flash('Пользователь не найден', 'error')
            return redirect(url_for('manage_users'))
        
        if request.method == 'POST':
            user.username = request.form['username']
            user.email = request.form['email']
            
            # Смена пароля (если указан)
            new_password = request.form.get('password', '').strip()
            if new_password:
                user.set_password(new_password)
            
            # Изменение роли (только для не-администраторов)
            if user.role != 'admin':
                user.role = request.form['role']
                
                # Если роль студент, привязываем к студенту
                if user.role == 'student':
                    student_id = request.form.get('student_id')
                    if student_id:
                        user.student_id = int(student_id)
                else:
                    user.student_id = None
            
            session.commit()
            flash('Пользователь обновлен!', 'success')
            return redirect(url_for('manage_users'))
        
        # Получаем список студентов без аккаунтов для формы
        student_ids_with_accounts = session.query(User.student_id).filter(User.student_id.isnot(None)).all()
        student_ids_with_accounts = [id[0] for id in student_ids_with_accounts]
        
        students_without_accounts = session.query(Student).filter(
            ~Student.id.in_(student_ids_with_accounts)
        ).all()
        
        return render_template('edit_user.html', user=user, students=students_without_accounts)

@app.route('/toggle_user_status/<int:user_id>')
@role_required('admin')
def toggle_user_status(user_id):
    with session_scope() as session:
        user = session.get(User, user_id)
        if user and user.role != 'admin':  # Нельзя блокировать администраторов
            user.is_active = not user.is_active
            session.commit()
            status = "активирован" if user.is_active else "заблокирован"
            flash(f'Пользователь {user.username} {status}', 'success')
        else:
            flash('Нельзя изменить статус администратора', 'error')
    return redirect(url_for('manage_users'))

@app.route('/delete_user/<int:user_id>')
@role_required('admin')
def delete_user(user_id):
    with session_scope() as session:
        user = session.get(User, user_id)
        if user and user.role != 'admin':  # Нельзя удалять администраторов
            username = user.username
            session.delete(user)
            session.commit()
            flash(f'Пользователь {username} удален', 'success')
        else:
            flash('Нельзя удалить администратора', 'error')
    return redirect(url_for('manage_users'))

@app.route('/approve_user/<int:user_id>')
@role_required('admin')
def approve_user(user_id):
    with session_scope() as session:
        user = session.get(User, user_id)
        if user and user.role == 'tutor':
            user.is_approved = True
            session.commit()
            flash(f'Пользователь {user.username} одобрен', 'success')
        else:
            flash('Пользователь не найден или не является репетитором', 'error')
    return redirect(url_for('manage_users'))

@app.route('/pending_approvals')
@role_required('admin')
def pending_approvals():
    with session_scope() as session:
        pending_users = session.query(User).filter_by(role='tutor', is_approved=False).all()
        return render_template('pending_approvals.html', users=pending_users)

@app.route('/delete_student/<int:student_id>')
@role_required('admin', 'tutor')
def delete_student(student_id):
    with session_scope() as session:
        student = session.get(Student, student_id)
        if student:
            student_name = student.full_name
            session.delete(student)
            session.commit()
            flash(f'Студент {student_name} и все связанные данные удалены', 'success')
        else:
            flash('Студент не найден', 'error')
    return redirect(url_for('all_students'))

@app.route('/cancel_lesson_web/<int:lesson_id>')
@role_required('admin', 'tutor')
def cancel_lesson_web(lesson_id):
    with session_scope() as session:
        lesson = session.get(Lesson, lesson_id)
        if lesson:
            lesson.status = 'отменен'
            session.commit()
            
            # Уведомляем студента
            student = lesson.student
            if student.telegram_chat_id and student.receive_notifications:
                from main_tg import send_notification
                lesson_time = lesson.date_time.strftime('%d.%m.%Y в %H:%M')
                send_notification(
                    student.telegram_chat_id,
                    f"❌ Занятие {lesson_time} отменено.\n"
                    f"Свяжитесь с репетитором для уточнения деталей."
                )
            
            flash(f'Урок с {student.full_name} отменен', 'success')
        else:
            flash('Урок не найден', 'error')
    
    # Перенаправляем туда, откуда пришли
    next_page = request.args.get('next', url_for('today_lessons'))
    return redirect(next_page)

@app.route('/edit_student_lessons_count/<int:student_id>', methods=['POST'])
@role_required('admin', 'tutor')
def edit_student_lessons_count(student_id):
    with session_scope() as session:
        student = session.get(Student, student_id)
        if student:
            try:
                new_count = int(request.form['lessons_count'])
                student.lessons_count = new_count
                session.commit()
                flash('Количество уроков обновлено!', 'success')
            except ValueError:
                flash('Неверное количество уроков', 'error')
        else:
            flash('Студент не найден', 'error')
    return redirect(url_for('view_student_card', student_id=student_id))

@app.route('/toggle_student_notifications/<int:student_id>', methods=['POST'])
@role_required('admin', 'tutor')
def toggle_student_notifications(student_id):
    with session_scope() as session:
        student = session.get(Student, student_id)
        if student:
            student.receive_notifications = not student.receive_notifications
            session.commit()
            status = "включены" if student.receive_notifications else "отключены"
            flash(f'Уведомления для {student.full_name} {status}', 'success')
        else:
            flash('Студент не найден', 'error')
    return redirect(url_for('view_student_card', student_id=student_id))

@app.route('/add_payment/<int:student_id>', methods=['GET', 'POST'])
@role_required('admin', 'tutor')
def add_payment(student_id):
    with session_scope() as session:
        student = session.get(Student, student_id)
        if not student:
            flash('Студент не найден', 'error')
            return redirect(url_for('all_students'))
        
        if request.method == 'POST':
            try:
                payment = Payment(
                    student_id=student_id,
                    amount=float(request.form['amount']),
                    description=request.form.get('description', '').strip(),
                    payment_date=datetime.strptime(request.form['payment_date'], '%Y-%m-%d') if request.form['payment_date'] else datetime.now()
                )
                session.add(payment)
                session.commit()
                
                flash('Платеж добавлен!', 'success')
                return redirect(url_for('view_student_card', student_id=student_id))
            except ValueError:
                flash('Неверная сумма платежа', 'error')
        
        return render_template('add_payment.html', student=student, today=datetime.now().strftime('%Y-%m-%d'))

@app.route('/students_homeworks/<int:student_id>')
@role_required('admin', 'tutor')
def students_homeworks(student_id):
    with session_scope() as session:
        student = session.get(Student, student_id)
        if not student:
            flash('Студент не найден', 'error')
            return redirect(url_for('all_students'))
        
        homeworks = session.query(Homework).filter_by(student_id=student_id).order_by(Homework.due_date.desc()).all()
        
        return render_template('students_homeworks.html', student=student, homeworks=homeworks)

@app.route('/edit_homework/<int:homework_id>', methods=['GET', 'POST'])
@role_required('admin', 'tutor')
def edit_homework(homework_id):
    with session_scope() as session:
        homework = session.get(Homework, homework_id)
        if not homework:
            flash('Домашнее задание не найдено', 'error')
            return redirect(url_for('pending_homeworks'))
        
        if request.method == 'POST':
            homework.description = request.form['description']
            homework.due_date = datetime.strptime(request.form['due_date'], '%Y-%m-%d') if request.form['due_date'] else None
            session.commit()
            
            flash('Домашнее задание обновлено!', 'success')
            return redirect(url_for('students_homeworks', student_id=homework.student_id))
        
        return render_template('edit_homework.html', homework=homework)

@app.route('/add_parent/<int:student_id>', methods=['GET', 'POST'])
@role_required('admin', 'tutor')
def add_parent(student_id):
    with session_scope() as session:
        student = session.get(Student, student_id)
        if not student:
            flash('Студент не найден', 'error')
            return redirect(url_for('all_students'))
        
        if request.method == 'POST':
            parent = Parent(
                student_id=student_id,
                telegram_chat_id=request.form['telegram_chat_id']
            )
            try:
                session.add(parent)
                session.commit()
                flash('Родитель добавлен!', 'success')
                return redirect(url_for('view_student_card', student_id=student_id))
            except Exception as e:
                flash('Ошибка добавления родителя (возможно, уже существует)', 'error')
        
        return render_template('add_parent.html', student=student)

@app.route('/invite_student/<int:student_id>')
@role_required('admin', 'tutor')
def invite_student(student_id):
    with session_scope() as session:
        student = session.get(Student, student_id)
        if not student:
            flash('Студент не найден', 'error')
            return redirect(url_for('all_students'))
        
        # Проверяем, есть ли уже аккаунт у студента
        existing_account = session.query(User).filter_by(student_id=student_id).first()
        if existing_account:
            flash('У этого студента уже есть аккаунт', 'error')
            return redirect(url_for('view_student_card', student_id=student_id))
        
        # Создаем приглашение
        invitation = Invitation(
            email=f"student{student_id}@example.com",  # Временный email
            role='student',
            student_id=student_id,
            created_by=flask_session['user_id'],
            expires_at=datetime.now() + timedelta(days=7)
        )
        invitation.generate_token()
        session.add(invitation)
        session.commit()
        
        invite_url = url_for('register', token=invitation.token, _external=True)
        flash(f'Приглашение создано! Ссылка: {invite_url}', 'success')
        
    return redirect(url_for('view_student_card', student_id=student_id))

@app.route('/confirm_homework_tutor/<int:homework_id>')
@role_required('admin', 'tutor')
def confirm_homework_tutor(homework_id):
    with session_scope() as session:
        homework = session.get(Homework, homework_id)
        if homework and homework.submitted_date and not homework.is_confirmed_by_tutor:
            homework.is_confirmed_by_tutor = True
            homework.completed_date = datetime.now()
            session.commit()
            
            # Уведомляем студента
            student = homework.student
            if student.telegram_chat_id and student.receive_notifications:
                from main_tg import send_notification
                send_notification(
                    student.telegram_chat_id,
                    f"✅ Ваше домашнее задание проверено и принято!\n\n"
                    f"Задание: {homework.description}"
                )
            
            flash('Домашнее задание подтверждено!', 'success')
        else:
            flash('Ошибка подтверждения домашнего задания', 'error')
    
    return redirect(url_for('students_homeworks', student_id=homework.student_id))

@app.route('/mark_homework_incomplete/<int:homework_id>')
@role_required('admin', 'tutor')
def mark_homework_incomplete(homework_id):
    with session_scope() as session:
        homework = session.get(Homework, homework_id)
        if homework:
            homework.is_completed = False
            homework.is_confirmed_by_tutor = False
            homework.submitted_date = None
            homework.student_comment = ""
            session.commit()
            
            # Уведомляем студента
            student = homework.student
            if student.telegram_chat_id and student.receive_notifications:
                from main_tg import send_notification
                send_notification(
                    student.telegram_chat_id,
                    f"❌ Ваше домашнее задание отклонено. Необходимо выполнить заново.\n\n"
                    f"Задание: {homework.description}"
                )
            
            flash('Домашнее задание отмечено как невыполненное', 'success')
        else:
            flash('Домашнее задание не найдено', 'error')
    
    return redirect(url_for('students_homeworks', student_id=homework.student_id))

@app.route('/mark_homework_completed_web/<int:homework_id>')
@role_required('admin', 'tutor')
def mark_homework_completed_web(homework_id):
    with session_scope() as session:
        homework = session.get(Homework, homework_id)
        if homework:
            homework.is_completed = True
            homework.is_confirmed_by_tutor = True
            homework.completed_date = datetime.now()
            if not homework.submitted_date:
                homework.submitted_date = datetime.now()
            session.commit()
            
            # Уведомляем студента
            student = homework.student
            if student.telegram_chat_id and student.receive_notifications:
                from main_tg import send_notification
                send_notification(
                    student.telegram_chat_id,
                    f"✅ Ваше домашнее задание отмечено как выполненное!\n\n"
                    f"Задание: {homework.description}"
                )
            
            flash('Домашнее задание отмечено как выполненное', 'success')
        else:
            flash('Домашнее задание не найдено', 'error')
    
    return redirect(url_for('students_homeworks', student_id=homework.student_id))

# Функция для создания администратора по умолчанию
def create_default_admin():
    # Проверяем миграции перед созданием администратора
    if not check_and_migrate_if_needed():
        print("❌ Не удалось проверить/обновить базу данных")
        return False
    
    try:
        with session_scope() as session:
            admin = session.query(User).filter_by(role='admin').first()
            if not admin:
                admin = User(
                    username='admin',
                    email='admin@tutorapp.com',
                    role='admin',
                    is_approved=True
                )
                admin.set_password('admin123')
                session.add(admin)
                session.commit()
                print("Создан администратор по умолчанию: admin / admin123")
            return True
    except Exception as e:
        print(f"❌ Ошибка создания администратора: {e}")
        return False

if __name__ == '__main__':
    create_default_admin()
    app.run(debug=True, port=5000)