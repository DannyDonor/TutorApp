from flask import Flask, render_template, request, redirect, session as flask_session, url_for, flash
from threading import Thread
from database import Session, Student, Lesson, Tutor, Parent, Homework, Payment, User, Invitation
import config
import telebot
from telebot import types
from datetime import datetime, timedelta, time
import time # <--- НОВЫЙ ИМПОРТ: добавляем import time
from contextlib import contextmanager
from sqlalchemy.exc import SQLAlchemyError
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

bot = telebot.TeleBot(config.BOT_TOKEN)

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

@app.context_processor
def inject_pending_homeworks_count():
    """Добавляет количество ожидающих проверки домашних заданий в контекст всех шаблонов"""
    if flask_session.get('role') in ['admin', 'tutor']:
        try:
            with session_scope() as session:
                pending_count = session.query(Homework).filter(
                    Homework.submitted_date.isnot(None),
                    Homework.is_confirmed_by_tutor == False
                ).count()
                return {'pending_homeworks_count': pending_count}
        except:
            return {'pending_homeworks_count': 0}
    return {'pending_homeworks_count': 0}

@app.before_request
def require_login():
    allowed = ['login', 'register', 'forgot_password', 'reset_password', 'static']
    if 'user_id' not in flask_session and request.endpoint not in allowed:
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
                
                flask_session['user_id'] = user.id
                flask_session['username'] = user.username
                flask_session['role'] = user.role
                flask_session['logged_in'] = True
                
                if user.role == 'student':
                    flask_session['student_id'] = user.student_id
                
                flash('Добро пожаловать!', 'success')
                return redirect(url_for('index'))
            else:
                flash('Неверный логин или пароль', 'error')
    
    return render_template('login.html')

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

@app.route('/logout')
def logout():
    flask_session.clear()
    flash('Вы успешно вышли из системы', 'success')
    return redirect(url_for('login'))

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
        current_user = session.query(User).filter_by(username=flask_session['username']).first()
        
        if request.method == 'POST':
            # Обновление токена бота
            bot_token = request.form.get('bot_token', '').strip()
            if bot_token:
                current_user.bot_token = bot_token
            
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

@app.route('/')
def index():
    if flask_session.get('role') == 'student':
        return redirect(url_for('student_dashboard'))
    else:
        return redirect(url_for('today_lessons'))

@app.route('/add_student', methods=['GET', 'POST'])
@role_required('admin', 'tutor')
def add_student():
    if request.method == 'POST':
        with session_scope() as session:
            student = Student(
                full_name=request.form['full_name'],
                lessons_count=int(request.form['lessons_count']),
                telegram_chat_id=request.form['telegram_chat_id'],
                receive_notifications=True
            )
            session.add(student)
            session.flush()  # Получаем ID студента
            
            # Автоматически создаем аккаунт для студента
            create_account = request.form.get('create_account') == 'on'
            if create_account:
                username = request.form.get('username')
                email = request.form.get('email')
                password = request.form.get('password', 'student123')  # Пароль по умолчанию
                
                if username and email:
                    # Проверяем уникальность
                    if not session.query(User).filter_by(username=username).first() and \
                       not session.query(User).filter_by(email=email).first():
                        user = User(
                            username=username,
                            email=email,
                            role='student',
                            student_id=student.id
                        )
                        user.set_password(password)
                        session.add(user)
                        flash(f'Студент и аккаунт успешно созданы! Логин: {username}, Пароль: {password}', 'success')
                    else:
                        flash('Студент создан, но аккаунт не создан - логин или email уже существует', 'error')
                else:
                    flash('Студент создан, но аккаунт не создан - не указаны логин или email', 'error')
            else:
                flash('Студент успешно создан!', 'success')
                
        return redirect('/students')
    return render_template('add_student.html')

@app.route('/add_lesson', methods=['GET', 'POST'])
@role_required('admin', 'tutor')
def add_lesson():
    with session_scope() as session:
        students = session.query(Student).all()
        if request.method == 'POST':
            student_id = int(request.form['student_id'])
            date_time = datetime.strptime(request.form['date_time'], "%Y-%m-%dT%H:%M")
            lesson = Lesson(student_id=student_id, date_time=date_time)
            session.add(lesson)
            student = session.get(Student, student_id)
            if student.receive_notifications:
                send_reminder(student, date_time, 'lesson_scheduled')
            return redirect('/all_lessons')
        return render_template('add_lesson.html', students=students)

@app.route('/delete_student/<int:student_id>')
@role_required('admin', 'tutor')
def delete_student(student_id):
    with session_scope() as session:
        student = session.get(Student, student_id)
        if student:
            session.delete(student)
        return redirect('/students')

@app.route('/student/<int:student_id>/add_parent', methods=['GET', 'POST'])
@role_required('admin', 'tutor')
def add_parent(student_id):
    with session_scope() as session:
        student = session.get(Student, student_id)
        if not student:
            return "Student not found", 404

        if request.method == 'POST':
            telegram_chat_id = request.form['telegram_chat_id'].strip()
            if telegram_chat_id:
                existing_parent = session.query(Parent).filter_by(student_id=student.id, telegram_chat_id=telegram_chat_id).first()
                if not existing_parent:
                    parent = Parent(student_id=student.id, telegram_chat_id=telegram_chat_id)
                    session.add(parent)
                    if student.receive_notifications and student.telegram_chat_id:
                        send_notification(student.telegram_chat_id, f"Поздравляем! Ваш родитель добавлен в систему: {telegram_chat_id}. Теперь он будет получать уведомления о ваших занятиях.")
                    send_notification(telegram_chat_id, f"Вы добавлены как родитель студента {student.full_name}. Вы будете получать уведомления о его занятиях.")
                    return redirect(url_for('view_student_card', student_id=student_id))
                else:
                    return "Родитель с таким Chat ID уже привязан к этому студенту.", 409
            return "Chat ID не может быть пустым.", 400
        return render_template('add_parent.html', student=student)

@app.route('/student/<int:student_id>/delete_parent/<int:parent_id>')
@role_required('admin', 'tutor')
def delete_parent(student_id, parent_id):
    with session_scope() as session:
        parent = session.get(Parent, parent_id)
        if parent and parent.student_id == student_id:
            student = parent.student
            session.delete(parent)
            send_notification(parent.telegram_chat_id, f"Вы удалены из списка родителей студента {student.full_name}.")
            if student.receive_notifications and student.telegram_chat_id:
                send_notification(student.telegram_chat_id, f"Ваш родитель с Chat ID {parent.telegram_chat_id} был удален из системы.")
        return redirect(url_for('view_student_card', student_id=student_id))

@app.route('/student/<int:student_id>/add_payment', methods=['GET', 'POST'])
@role_required('admin', 'tutor')
def add_payment(student_id):
    with session_scope() as session:
        student = session.get(Student, student_id)
        if not student:
            return "Student not found", 404

        if request.method == 'POST':
            try:
                amount = float(request.form['amount'])
                description = request.form['description']
                payment = Payment(student_id=student.id, amount=amount, description=description)
                session.add(payment)
                if student.receive_notifications and student.telegram_chat_id:
                    send_notification(student.telegram_chat_id, f"✅ Платеж на сумму {amount} руб. от вас или вашего родителя зачислен на счет {student.full_name}. ({description or 'Без описания'})")
                for parent in student.parents:
                    send_notification(parent.telegram_chat_id, f"✅ Платеж на сумму {amount} руб. за студента {student.full_name} зачислен. ({description or 'Без описания'})")
                return redirect(url_for('view_student_card', student_id=student_id))
            except ValueError:
                return "Неверный формат суммы.", 400
        return render_template('add_payment.html', student=student)

@app.route('/delete_payment/<int:payment_id>')
@role_required('admin', 'tutor')
def delete_payment(payment_id):
    with session_scope() as session:
        payment = session.get(Payment, payment_id)
        if payment:
            student_id = payment.student_id
            session.delete(payment)
        return redirect(url_for('view_student_card', student_id=student_id))

@app.route('/edit_student_lessons_count/<int:student_id>', methods=['POST'])
@role_required('admin', 'tutor')
def edit_student_lessons_count(student_id):
    with session_scope() as session:
        student = session.get(Student, student_id)
        if not student:
            return "Student not found", 404

        try:
            new_lessons_count = int(request.form['lessons_count'])
            student.lessons_count = new_lessons_count
            return redirect(url_for('view_student_card', student_id=student_id))
        except ValueError:
            return "Неверное количество занятий.", 400

@app.route('/toggle_student_notifications/<int:student_id>', methods=['POST'])
@role_required('admin', 'tutor')
def toggle_student_notifications(student_id):
    with session_scope() as session:
        student = session.get(Student, student_id)
        if not student:
            return "Student not found", 404

        student.receive_notifications = not student.receive_notifications

        status = "включены" if student.receive_notifications else "отключены"
        send_tutor_notification(f"Уведомления для студента {student.full_name} теперь {status}.")
        if student.telegram_chat_id:
            send_notification(student.telegram_chat_id, f"Ваши уведомления теперь {status}.")

        return redirect(url_for('view_student_card', student_id=student_id))


@app.route('/student/<int:student_id>')
def view_student_card(student_id):
    # Проверяем права доступа
    user_role = flask_session.get('role')
    if user_role == 'student':
        # Студенты могут видеть только свою карточку
        if flask_session.get('student_id') != student_id:
            flash('У вас нет прав для просмотра этой карточки', 'error')
            return redirect(url_for('student_dashboard'))
    elif user_role not in ['admin', 'tutor']:
        flash('У вас нет прав для доступа к этой странице', 'error')
        return redirect(url_for('login'))
    
    with session_scope() as session:
        student = session.get(Student, student_id)
        if not student:
            return "Student not found", 404

        parents = session.query(Parent).filter_by(student_id=student.id).all()
        lessons = session.query(Lesson).filter_by(student_id=student.id).order_by(Lesson.date_time.asc()).all()
        homeworks = session.query(Homework).filter_by(student_id=student.id).order_by(Homework.due_date.desc(), Homework.id.desc()).all()
        payments = session.query(Payment).filter_by(student_id=student.id).order_by(Payment.payment_date.desc()).all()

        return render_template('student_card.html',
                               student=student,
                               parents=parents,
                               lessons=lessons,
                               homeworks=homeworks,
                               payments=payments)


@app.route('/students')
@role_required('admin', 'tutor')
def all_students():
    with session_scope() as session:
        search_query = request.args.get('search', '').strip()
        if search_query:
            students = session.query(Student).filter(
                or_(
                    Student.full_name.ilike(f'%{search_query}%'),
                    Student.telegram_chat_id.ilike(f'%{search_query}%')
                )
            ).all()
        else:
            students = session.query(Student).all()
        return render_template('all_students.html', students=students, search_query=search_query)

@app.route('/all_lessons')
@role_required('admin', 'tutor')
def all_lessons():
    with session_scope() as session:
        lessons = session.query(Lesson).order_by(Lesson.date_time.asc()).all()
        return render_template('all_lessons.html', lessons=lessons)

@app.route('/today')
def today_lessons():
    with session_scope() as session:
        today = datetime.now().date()
        start_of_day = datetime.combine(today, datetime.min.time())
        end_of_day = datetime.combine(today, datetime.max.time())

        lessons = session.query(Lesson).filter(
            Lesson.date_time >= start_of_day,
            Lesson.date_time <= end_of_day,
            Lesson.status == 'запланирован'
        ).order_by(Lesson.date_time).all()

        return render_template('today_lessons.html', lessons=lessons, today=today.strftime('%d.%m.%Y'))


@app.route('/edit_lesson/<int:lesson_id>', methods=['GET', 'POST'])
@role_required('admin', 'tutor')
def edit_lesson(lesson_id):
    with session_scope() as session:
        lesson = session.get(Lesson, lesson_id)
        if not lesson:
            return "Занятие не найдено", 404

        student = lesson.student # Получаем студента, связанного с занятием

        if request.method == 'POST':
            old_status = lesson.status # Сохраняем старый статус занятия

            # Обновление времени занятия
            lesson.date_time = datetime.strptime(request.form['date_time'], '%Y-%m-%dT%H:%M')

            # Обновление статуса занятия и связанного с ним баланса
            new_status = request.form.get('report_status') # Это поле из edit_lesson.html
            lesson.status = new_status

            # Логика для изменения количества занятий у студента
            if old_status != 'проведен' and new_status == 'проведен':
                # Занятие только что стало 'completed' (было 'scheduled', 'cancelled', 'no_show')
                if student.lessons_count > 0:
                    student.lessons_count -= 1
                    send_notification(config.TUTOR_ID, f"➖ Урок со студентом {student.full_name} ({lesson.date_time.strftime('%d.%m.%Y %H:%M')}) отмечен как проведенный. Осталось занятий: {student.lessons_count}.")
                    if student.telegram_chat_id and student.receive_notifications:
                        send_notification(student.telegram_chat_id, f"🎉 Урок {lesson.date_time.strftime('%d.%m.%Y %H:%M')} успешно проведен! Осталось занятий: {student.lessons_count}.")
                else:
                    send_notification(config.TUTOR_ID, f"❗Урок со студентом {student.full_name} ({lesson.date_time.strftime('%d.%m.%Y %H:%M')}) отмечен как проведенный, но баланс занятий уже 0. Проверьте баланс.")
            elif old_status == 'completed' and new_status != 'completed':
                # Занятие было 'completed', но теперь изменилось на другой статус (отменено, не пришел и т.д.)
                student.lessons_count += 1
                send_notification(config.TUTOR_ID, f"➕ Статус урока со студентом {student.full_name} ({lesson.date_time.strftime('%d.%m.%Y %H:%M')}) изменен с 'проведенный'. Баланс занятий восстановлен: {student.lessons_count}.")
                if student.telegram_chat_id and student.receive_notifications:
                    send_notification(student.telegram_chat_id, f"🚫 Статус урока {lesson.date_time.strftime('%d.%m.%Y %H:%M')} изменен. Баланс занятий восстановлен: {student.lessons_count}.")
            # Если old_status и new_status одинаковы или не связаны с 'completed', ничего не делаем с lessons_count


            # Обновление полей отчета
            lesson.topic_covered = request.form.get('topic_covered')
            lesson.video_status = request.form.get('video_status', 'pending')
            
            # Обработка видео ссылки в зависимости от статуса
            if lesson.video_status == 'added':
                lesson.video_link = request.form.get('video_link')
            elif lesson.video_status == 'later':
                lesson.video_link = None  # Очищаем ссылку, если добавляем позже
            
            lesson.report_status = new_status # Также обновляем report_status

            # Обработка домашнего задания
            homework_description = request.form.get('homework_description')
            if homework_description:
                if lesson.homework:
                    lesson.homework.description = homework_description
                    lesson.homework.due_date = lesson.date_time + timedelta(days=7) # Обновляем срок, если есть
                else:
                    new_homework = Homework(
                        student_id=student.id,
                        lesson_id=lesson.id,
                        description=homework_description,
                        due_date=lesson.date_time + timedelta(days=7), # Пример: через 7 дней от даты урока
                        is_completed=False # Новое ДЗ по умолчанию не выполнено
                    )
                    session.add(new_homework)
                    send_notification(config.TUTOR_ID, f"📝 Новое домашнее задание для {student.full_name}: '{homework_description}' со сроком {new_homework.due_date.strftime('%d.%m.%Y')}.")
                    if student.telegram_chat_id and student.receive_notifications:
                        send_notification(student.telegram_chat_id, f"📝 Вам выдано новое домашнее задание: '{homework_description}' со сроком {new_homework.due_date.strftime('%d.%m.%Y')}.")
            elif lesson.homework: # Если описание ДЗ удалено из формы, а ДЗ существует, удаляем его
                send_notification(config.TUTOR_ID, f"🗑️ Домашнее задание '{lesson.homework.description}' студента {student.full_name} удалено.")
                session.delete(lesson.homework)


            # Обработка следующего занятия (автоматическое создание)
            next_lesson_date_str = request.form.get('next_lesson_date')
            if next_lesson_date_str:
                next_lesson_date_time = datetime.strptime(next_lesson_date_str, '%Y-%m-%dT%H:%M')
                # Проверяем, нет ли уже такого занятия, чтобы избежать дубликатов
                existing_next_lesson = session.query(Lesson).filter_by(
                    student_id=student.id,
                    date_time=next_lesson_date_time,
                    status='scheduled'
                ).first()

                if not existing_next_lesson:
                    new_lesson = Lesson(student_id=student.id, date_time=next_lesson_date_time, status='scheduled')
                    # Если занятие только что создано, добавляем 1 к счетчику
                    # (это отдельное действие от изменения статуса текущего урока)
                    student.lessons_count += 1
                    session.add(new_lesson)
                    send_notification(config.TUTOR_ID, f"🗓️ Для студента {student.full_name} запланировано новое занятие на {next_lesson_date_time.strftime('%d.%m.%Y %H:%M')}. Баланс занятий: {student.lessons_count}.")
                    if student.telegram_chat_id and student.receive_notifications:
                        send_notification(student.telegram_chat_id, f"🗓️ Для вас запланировано новое занятие на {next_lesson_date_time.strftime('%d.%m.%Y %H:%M')}. Баланс занятий: {student.lessons_count}.")
                else:
                    send_notification(config.TUTOR_ID, f"🚫 Попытка создать дубликат следующего занятия для {student.full_name} на {next_lesson_date_time.strftime('%d.%m.%Y %H:%M')}.")


            session.add(lesson) # Сохраняем изменения в текущем занятии
            session.add(student) # Сохраняем изменения в студенте (lessons_count)
            # session.commit() # Commit happens automatically due to session_scope

            return redirect(url_for('today_lessons')) # Перенаправление после сохранения

        # GET request: Render the form
        current_time = lesson.date_time.strftime('%Y-%m-%dT%H:%M')
        return render_template('edit_lesson.html', lesson=lesson, student=student, current_time=current_time)

@app.route('/cancel_lesson_web/<int:lesson_id>') # <--- ИЗМЕНЕНО: название маршрута
@role_required('admin', 'tutor')
def cancel_lesson_web(lesson_id): # <--- ИЗМЕНЕНО: название функции
    next_url = request.args.get('next') # <--- НОВОЕ: Получаем параметр 'next' из URL
    if not next_url: # Если next параметр не передан, устанавливаем дефолтный URL
        # Выберите дефолтный URL, который вам больше подходит.
        # Например, 'all_lessons' или 'today_lessons'
        next_url = url_for('all_lessons') # <--- ВАЖНО: Дефолтное перенаправление

    with session_scope() as session:
        lesson = session.get(Lesson, lesson_id)
        if lesson:
            student = lesson.student
            # Логика отмены (статус, баланс, уведомления) остается без изменений
            if lesson.status == 'scheduled' or lesson.status == 'completed':
                lesson.status = 'cancelled'
                student.lessons_count += 1
                session.add(lesson)
                session.add(student)
                send_notification(config.TUTOR_ID, f"❌ Занятие студента {student.full_name} на {lesson.date_time.strftime('%d.%m.%Y %H:%M')} отменено. Количество занятий студента увеличено на 1. Текущий баланс: {student.lessons_count}")
                if student.telegram_chat_id and student.receive_notifications:
                    send_notification(student.telegram_chat_id, f"❌ Занятие на {lesson.date_time.strftime('%d.%m.%Y %H:%M')} отменено.")
            else:
                send_notification(config.TUTOR_ID, f"Занятие студента {student.full_name} на {lesson.date_time.strftime('%d.%m.%Y %H:%M')} уже имеет статус '{lesson.status}'. Количество занятий не изменено.")

        return redirect(next_url) # <--- ИЗМЕНЕНО: Перенаправляем на URL, полученный из параметра 'next'

@app.route('/mark_homework_completed_web/<int:homework_id>')
@role_required('admin', 'tutor')
def mark_homework_completed_web(homework_id):
    student_id = None
    
    with session_scope() as session:
        homework = session.get(Homework, homework_id)
        if homework:
            student_id = homework.student_id  # Сохраняем student_id до закрытия сессии
            homework.is_completed = True
            homework.is_confirmed_by_tutor = True
            homework.completed_date = datetime.now()
            
            # Уведомляем студента о подтверждении
            if homework.student.telegram_chat_id and homework.student.receive_notifications:
                send_notification(homework.student.telegram_chat_id, 
                    f"✅ Ваше домашнее задание '{homework.description}' подтверждено репетитором!")
            
            flash('Домашнее задание подтверждено!', 'success')
    
    if student_id:
        return redirect(url_for('students_homeworks', student_id=student_id))
    else:
        return redirect(url_for('pending_homeworks'))

@app.route('/confirm_homework_tutor/<int:homework_id>')
@role_required('admin', 'tutor')
def confirm_homework_tutor(homework_id):
    student_id = None
    
    with session_scope() as session:
        homework = session.get(Homework, homework_id)
        if homework and homework.submitted_date and not homework.is_confirmed_by_tutor:
            student_id = homework.student_id  # Сохраняем student_id до закрытия сессии
            homework.is_confirmed_by_tutor = True
            homework.completed_date = datetime.now()
            
            # Уведомляем студента о подтверждении
            if homework.student.telegram_chat_id and homework.student.receive_notifications:
                send_notification(homework.student.telegram_chat_id, 
                    f"✅ Ваше домашнее задание '{homework.description}' подтверждено репетитором!")
            
            flash('Домашнее задание подтверждено!', 'success')
        elif homework:
            student_id = homework.student_id  # Сохраняем student_id даже если задание уже подтверждено
            flash('Домашнее задание не найдено или уже подтверждено', 'error')
        else:
            flash('Домашнее задание не найдено', 'error')
    
    # Определяем, откуда пришел запрос, и перенаправляем обратно
    next_url = request.args.get('next')
    if next_url:
        return redirect(next_url)
    elif student_id:
        return redirect(url_for('students_homeworks', student_id=student_id))
    else:
        return redirect(url_for('pending_homeworks'))


# --- Telegram Bot Handlers ---

def send_notification(chat_id, message_text, reply_markup=None):
    if not chat_id:
        return

    with session_scope() as s:
        tutor = s.query(Tutor).first()
        if tutor and str(chat_id) == tutor.chat_id:
            try:
                return bot.send_message(chat_id, message_text, reply_markup=reply_markup)
            except telebot.apihelper.ApiTelegramException as e:
                print(f"Ошибка отправки сообщения репетитору (чат ID: {chat_id}): {e}")
            except Exception as e:
                print(f"Неизвестная ошибка при отправке сообщения репетитору (чат ID: {chat_id}): {e}")
            return

    is_student_or_parent = False
    with session_scope() as s:
        student = s.query(Student).filter_by(telegram_chat_id=str(chat_id)).first()
        if student:
            is_student_or_parent = True
            if not student.receive_notifications:
                print(f"Уведомления для студента {student.full_name} (ID: {chat_id}) отключены. Сообщение не отправлено.")
                return

        if not student:
            parent = s.query(Parent).filter_by(telegram_chat_id=str(chat_id)).first()
            if parent:
                is_student_or_parent = True
                if not parent.student.receive_notifications:
                    print(f"Уведомления для родителя {chat_id} (студент {parent.student.full_name}) отключены, т.к. уведомления студента отключены. Сообщение не отправлено.")
                    return


    try:
        return bot.send_message(chat_id, message_text, reply_markup=reply_markup)
    except telebot.apihelper.ApiTelegramException as e:
        error_message = f"Ошибка отправки сообщения в Telegram (чат ID: {chat_id}): {e}"
        print(error_message)
        send_tutor_notification(error_message)
    except Exception as e:
        error_message = f"Неизвестная ошибка при отправке сообщения в Telegram (чат ID: {chat_id}): {e}"
        print(error_message)
        send_tutor_notification(error_message)
    return None


def send_tutor_notification(message_text):
    """Sends a notification to the tutor."""
    with session_scope() as session:
        tutor = session.query(Tutor).first()
        if tutor and tutor.chat_id:
            try:
                bot.send_message(tutor.chat_id, f"⚠️ УВЕДОМЛЕНИЕ (ПРЕПОДАВАТЕЛЮ):\n{message_text}")
            except Exception as e:
                print(f"Критическая ошибка: не удалось отправить уведомление репетитору: {e}")


def send_reminder(student, lesson_time, reminder_type):
    if not student.receive_notifications:
        return

    message_text = ""
    if reminder_type == 'lesson_scheduled':
        message_text = f"🔔 Напоминание: {student.full_name}, занятие назначено на {lesson_time.strftime('%Y-%m-%d %H:%M')}"
    elif reminder_type == '30_min_before':
        message_text = f"🔔 Напоминание: {student.full_name}, занятие через 30 минут 🕒 {lesson_time.strftime('%d.%m.%Y %H:%M')}"
    elif reminder_type == '1_hour_before_tutor':
        message_text = f"⏰ Через 1 час занятие с {student.full_name} в {lesson_time.strftime('%H:%M')}"
    elif reminder_type == 'homework_due':
        message_text = f"⏰ Напоминание: Домашнее задание к занятию с {student.full_name} в {lesson_time.strftime('%H:%M')} еще не сдано.\n"

    if student.telegram_chat_id:
        send_notification(student.telegram_chat_id, message_text)

    with session_scope() as session:
        parents = session.query(Parent).filter_by(student_id=student.id).all()
        for parent in parents:
            send_notification(parent.telegram_chat_id, message_text)

    if reminder_type == '1_hour_before_tutor':
        with session_scope() as session:
            tutor = session.query(Tutor).first()
            if tutor and tutor.chat_id:
                send_notification(tutor.chat_id, message_text)


def send_lesson_report(lesson, student, report_status, homework_description=None):
    message_to_student = ""
    message_to_parents = ""

    if report_status == 'completed':
        message_to_student = (
            f"✅ Ваше занятие от {lesson.date_time.strftime('%d.%m.%Y %H:%M')} завершено!\n"
            f"Тема: {lesson.topic_covered or 'Не указана'}\n"
        )
        message_to_parents = (
            f"✅ Занятие вашего ребенка {student.full_name} от {lesson.date_time.strftime('%d.%m.%Y %H:%M')} завершено!\n"
            f"Тема: {lesson.topic_covered or 'Не указана'}\n"
        )
        if lesson.video_link:
            message_to_student += f"Запись урока: {lesson.video_link}\n"
            message_to_parents += f"Запись урока: {lesson.video_link}\n"
        if homework_description:
            message_to_student += f"\n📄 Домашнее задание: {homework_description}\n"
            message_to_parents += f"\n📄 Домашнее задание для {student.full_name}: {homework_description}\n"
        if lesson.next_lesson_date:
            message_to_student += f"Следующее занятие запланировано на: {lesson.next_lesson_date.strftime('%d.%m.%Y %H:%M')}"
            message_to_parents += f"Следующее занятие для {student.full_name} запланировано на: {lesson.next_lesson_date.strftime('%d.%m.%Y %H:%M')}"

    elif report_status == 'cancelled':
        message_to_student = f"❌ Ваше занятие от {lesson.date_time.strftime('%d.%m.%Y %H:%M')} отменено."
        message_to_parents = f"❌ Занятие вашего ребенка {student.full_name} от {lesson.date_time.strftime('%d.%m.%Y %H:%M')} отменено."

    elif report_status == 'no_show':
        message_to_student = f"🚫 Вы не пришли на занятие от {lesson.date_time.strftime('%d.%m.%Y %H:%M')}."
        message_to_parents = f"🚫 Ваш ребенок {student.full_name} не пришел на занятие от {lesson.date_time.strftime('%d.%m.%Y %H:%M')}."

    if student.receive_notifications and student.telegram_chat_id and message_to_student:
        markup = None
        if homework_description:
            homework_obj = None
            with session_scope() as session_inner:
                homework_obj = session_inner.query(Homework).filter_by(lesson_id=lesson.id).first()
            if homework_obj:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("✅ Подтвердить выполнение ДЗ", callback_data=f"confirm_homework_{homework_obj.id}"))
        sent_message = send_notification(student.telegram_chat_id, message_to_student, markup)
        if sent_message and homework_obj:
             with session_scope() as session_inner:
                hw_to_update = session_inner.query(Homework).get(homework_obj.id)
                if hw_to_update:
                    hw_to_update.telegram_message_id = str(sent_message.message_id)


    with session_scope() as session_inner:
        parents = session_inner.query(Parent).filter_by(student_id=student.id).all()
        if message_to_parents:
            for parent in parents:
                send_notification(parent.telegram_chat_id, message_to_parents)


@app.route('/statistics')
@role_required('admin', 'tutor')
def statistics():
    with session_scope() as session:
        students_data = []
        students = session.query(Student).filter_by(is_archived=False).all()  # Исключаем архивированных студентов

        for student in students:
            completed_lessons = session.query(Lesson).filter_by(
                student_id=student.id,
                status='completed'
            ).count()

            no_show_lessons = session.query(Lesson).filter_by(
                student_id=student.id,
                status='no_show'
            ).count()

            cancelled_lessons = session.query(Lesson).filter_by(
                student_id=student.id,
                status='cancelled'
            ).count()

            scheduled_lessons = session.query(Lesson).filter_by(
                student_id=student.id,
                status='scheduled'
            ).count()

            students_data.append({
                'full_name': student.full_name,
                'current_balance': student.lessons_count,
                'total_completed_lessons': completed_lessons,
                'total_no_show_lessons': no_show_lessons,
                'total_cancelled_lessons': cancelled_lessons,
                'total_missed_lessons': no_show_lessons + cancelled_lessons,  # Сумма прогулов и отмен
                'total_scheduled_lessons': scheduled_lessons
            })
    return render_template('statistics.html', students_data=students_data)

def reminder_loop():
    while True:
        with session_scope() as session:
            tutor = session.query(Tutor).first()
            now = datetime.now()

            # --- Reminders for Lessons ---
            upcoming_lessons = session.query(Lesson).filter(
                Lesson.status == 'запланирован',
                Lesson.date_time > now
            ).all()

            for lesson in upcoming_lessons:
                student = session.get(Student, lesson.student_id)
                if not student:
                    continue

                if not student.receive_notifications:
                    continue

                diff = lesson.date_time - now

                if timedelta(minutes=25) < diff < timedelta(minutes=35):
                    send_reminder(student, lesson.date_time, '30_min_before')

                elif timedelta(minutes=55) < diff < timedelta(minutes=65):
                    if tutor and tutor.chat_id:
                        send_notification(tutor.chat_id, f"⏰ Через 1 час занятие с {student.full_name} в {lesson.date_time.strftime('%H:%M')}")


            # --- Reminders for Homework ---
            lessons_with_homework_due = session.query(Lesson).join(Homework).filter(
                Lesson.status == 'запланирован',
                Homework.is_completed == False,
                Lesson.date_time > now,
                (Lesson.date_time - now) < timedelta(hours=6)
            ).all()

            for lesson in lessons_with_homework_due:
                homework = lesson.homework
                student = session.get(Student, lesson.student_id)
                if student and student.telegram_id and student.receive_notifications:
                    send_notification(student.telegram_id,
                                      f"⏰ Напоминание: Домашнее задание к занятию с {student.full_name} в {lesson.date_time.strftime('%H:%M')} еще не сдано.\n"
                                      f"Задание: {homework.description}\n"
                                      f"Пожалуйста, подтвердите выполнение кнопкой под сообщением с ДЗ, или отправьте '/complete_homework_{homework.id}'")

        time.sleep(60)

@app.route('/mark_homework_incomplete/<int:homework_id>')
@role_required('admin', 'tutor')
def mark_homework_incomplete(homework_id):
    # По умолчанию перенаправляем на список студентов, если next не указан
    default_redirect_url = url_for('all_students')

    with session_scope() as session:
        homework = session.get(Homework, homework_id)
        if not homework:
            return redirect(default_redirect_url) # Если ДЗ не найдено

        student_id = homework.student_id # Получаем student_id из найденного ДЗ

        # Определяем URL для перенаправления.
        # Если next-параметр был передан, используем его.
        # Иначе, возвращаемся на страницу домашних заданий конкретного студента.
        next_url = request.args.get('next')
        if not next_url:
            # Здесь выбираем, куда возвращаться по умолчанию.
            # Если вы всегда переходите на ДЗ студента через students_homeworks.html, то:
            next_url = url_for('students_homeworks', student_id=student_id)
            # Если вы хотите возвращаться на карточку студента, то:
            # next_url = url_for('student_card', student_id=student_id)

        if homework.is_completed or homework.is_confirmed_by_tutor: # Если ДЗ выполнено или подтверждено, меняем на невыполнено
            homework.is_completed = False
            homework.is_confirmed_by_tutor = False
            homework.completed_date = None # Сбрасываем дату выполнения
            homework.submitted_date = None # Сбрасываем дату отправки

            session.add(homework)
            send_notification(config.TUTOR_ID, f"🔄 Домашнее задание '{homework.description}' студента {homework.student.full_name} помечено как НЕВЫПОЛНЕННОЕ.")
            if homework.student.telegram_chat_id and homework.student.receive_notifications:
                send_notification(homework.student.telegram_chat_id, f"🔄 Ваше домашнее задание '{homework.description}' помечено как НЕВЫПОЛНЕННОЕ. Необходимо выполнить заново.")
            
            flash('Домашнее задание отклонено и помечено как невыполненное', 'success')
        else:
            # Если ДЗ уже не выполнено, можно просто уведомить или ничего не делать
            flash('Домашнее задание уже имеет статус "не выполнено"', 'info')

    return redirect(next_url)

@app.route('/students_homeworks/<int:student_id>')
@role_required('admin', 'tutor')
def students_homeworks(student_id):
    with session_scope() as session:
        student = session.get(Student, student_id)
        if not student:
            return "Студент не найден", 404
        homeworks = session.query(Homework).filter_by(student_id=student.id).order_by(Homework.due_date.desc()).all()
        return render_template('students_homeworks.html', student=student, homeworks=homeworks)

@app.route('/pending_homeworks')
@role_required('admin', 'tutor')
def pending_homeworks():
    with session_scope() as session:
        # Получаем все домашние задания, которые отправлены студентами, но не подтверждены репетитором
        pending_homeworks = session.query(Homework).filter(
            Homework.submitted_date.isnot(None),
            Homework.is_confirmed_by_tutor == False
        ).order_by(Homework.submitted_date.asc()).all()
        
        return render_template('pending_homeworks.html', pending_homeworks=pending_homeworks)



@bot.message_handler(commands=['start'])
def handle_start(message):
    if message.from_user.username == config.TUTOR_ID:
        with session_scope() as session:
            existing_tutor = session.query(Tutor).filter_by(chat_id=str(message.chat.id)).first()
            if not existing_tutor:
                tutor = Tutor(chat_id=str(message.chat.id))
                session.add(tutor)
        send_tutor_menu(message.chat.id)
    else:
        with session_scope() as session:
            student = session.query(Student).filter_by(telegram_id=str(message.chat.id)).first()
            if student and student.receive_notifications:
                send_notification(message.chat.id, "Добро пожаловать. Когда твой наставник назначит тебе занятие, я пришлю тебе напоминания.")
            elif student and not student.receive_notifications:
                 send_notification(message.chat.id, "Добро пожаловать. Ваши уведомления отключены. Чтобы их включить, обратитесь к репетитору.")
            else:
                 send_notification(message.chat.id, "Добро пожаловать. Для начала работы попросите вашего репетитора добавить вас в систему.")


def send_tutor_menu(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton('📝 Список студентов')
    btn2 = types.KeyboardButton('➕ Добавить студента')
    btn3 = types.KeyboardButton('📅 Список занятий (бот)')
    btn4 = types.KeyboardButton('➕ Добавить занятие (бот)')
    btn5 = types.KeyboardButton('📅 Расписание на сегодня')
    markup.add(btn1, btn2, btn3, btn4, btn5)
    send_notification(
        chat_id,
        "👋 Добро пожаловать в систему управления репетиторством!\n\n"
        "Вы можете управлять студентами и занятиями прямо здесь.",
        reply_markup=markup
    )


@bot.message_handler(commands=['menu'])
def show_menu(message):
    if message.from_user.username == config.TUTOR_ID:
        send_tutor_menu(message.chat.id)
    else:
        send_notification(message.chat.id, "У вас нет доступа к этому меню.")


@bot.message_handler(func=lambda message: message.text == '📝 Список студентов')
def list_students_telebot(message): # Переименовал, чтобы не конфликтовал с веб-версией
    if message.from_user.username != config.TUTOR_ID: return
    with session_scope() as session:
        students = session.query(Student).all()
        if not students:
            send_notification(message.chat.id, "Нет студентов в базе.")
            return

        response = "Список студентов:\n\n"
        for student in students:
            response += f"👤 {student.full_name}\n"
            response += f"   Занятий (в базе): {len(student.lessons)}\n"
            response += f"   Telegram: @{student.telegram_id if student.telegram_id else 'Нет'}\n"
            response += f"   Уведомления: {'Включены' if student.receive_notifications else 'Отключены'}\n"
            parents = session.query(Parent).filter_by(student_id=student.id).all()
            if parents:
                response += "   Родители: " + ", ".join([p.telegram_id for p in parents]) + "\n"
            response += f"   [ID: {student.id}]\n\n"

        send_notification(message.chat.id, response)


@bot.message_handler(func=lambda message: message.text == '➕ Добавить студента')
def add_student_command(message):
    if message.from_user.username != config.TUTOR_ID: return
    msg = bot.send_message(message.chat.id,
                           "Введите данные студента в формате:\nФИО,Количество занятий,Telegram username\n\nПример: Иванов Иван Иванович,10,ivanov")
    bot.register_next_step_handler(msg, process_student_data)


def process_student_data(message):
    if message.from_user.username != config.TUTOR_ID: return
    try:
        data = message.text.split(',')
        if len(data) < 3:
            raise ValueError("Недостаточно данных")

        full_name = data[0].strip()
        lessons_count = int(data[1].strip())
        telegram_id = data[2].strip().replace('@', '') if data[2].strip() else None

        with session_scope() as session:
            student = Student(
                full_name=full_name,
                lessons_count=lessons_count,
                telegram_id=telegram_id,
                receive_notifications=True
            )
            session.add(student)

        send_notification(message.chat.id, f"✅ Студент {full_name} успешно добавлен!")
    except Exception as e:
        send_notification(message.chat.id, f"❌ Ошибка: {str(e)}")


@bot.message_handler(func=lambda message: message.text == '📅 Список занятий (бот)')
def list_lessons(message):
    if message.from_user.username != config.TUTOR_ID: return
    with session_scope() as session:
        lessons = session.query(Lesson).order_by(Lesson.date_time).all()

        if not lessons:
            send_notification(message.chat.id, "Нет запланированных занятий.")
            return

        response = "Ближайшие занятия:\n\n"
        for lesson in lessons:
            student = session.get(Student, lesson.student_id)
            status_emoji = "✅" if lesson.status == 'scheduled' else "❌" if lesson.status == 'cancelled' else "❓"
            response += f"{status_emoji} {lesson.date_time.strftime('%d.%m %H:%M')} - {student.full_name}\n"

        send_notification(message.chat.id, response)


@bot.message_handler(func=lambda message: message.text == '➕ Добавить занятие (бот)')
def add_lesson_command(message):
    if message.from_user.username != config.TUTOR_ID: return
    with session_scope() as session:
        students = session.query(Student).all()

        if not students:
            send_notification(message.chat.id, "Нет студентов в базе. Сначала добавьте студента.")
            return

        markup = types.InlineKeyboardMarkup()
        for student in students:
            markup.add(types.InlineKeyboardButton(
                text=f"{student.full_name} (ID: {student.id})",
                callback_data=f"add_lesson_{student.id}"
            ))

        send_notification(message.chat.id, "Выберите студента:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('add_lesson_'))
def choose_student_for_lesson(call):
    if call.from_user.username != config.TUTOR_ID: return
    student_id = int(call.data.split('_')[2])
    msg = bot.send_message(call.message.chat.id,
                           "Введите дату и время занятия в формате ДД.ММ.ГГГГ ЧЧ:ММ\n\nПример: 15.12.2023 14:30")
    bot.register_next_step_handler(msg, process_lesson_date, student_id)


def process_lesson_date(message, student_id):
    if message.from_user.username != config.TUTOR_ID: return
    try:
        date_time = datetime.strptime(message.text, "%d.%m.%Y %H:%M")
        with session_scope() as session:
            lesson = Lesson(
                student_id=student_id,
                date_time=date_time
            )
            session.add(lesson)

            student = session.get(Student, student_id)
            send_notification(message.chat.id,
                             f"✅ Занятие для {student.full_name} на {date_time.strftime('%d.%m.%Y %H:%M')} добавлено!")

            if student.receive_notifications:
                send_reminder(student, date_time, 'lesson_scheduled')
    except ValueError:
        send_notification(message.chat.id, "❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ ЧЧ:ММ")
    except Exception as e:
        send_notification(message.chat.id, f"❌ Ошибка: {str(e)}")


@bot.message_handler(commands=['cancel_lesson'])
def cancel_lesson_command(message):
    if message.from_user.username != config.TUTOR_ID: return
    with session_scope() as session:
        lessons = session.query(Lesson).filter(Lesson.status == 'scheduled').order_by(Lesson.date_time).all()

        if not lessons:
            send_notification(message.chat.id, "Нет активных занятий для отмены.")
            return

        markup = types.InlineKeyboardMarkup()
        for lesson in lessons:
            student = session.get(Student, lesson.student_id)
            markup.add(types.InlineKeyboardButton(
                text=f"{lesson.date_time.strftime('%d.%m %H:%M')} - {student.full_name}",
                callback_data=f"cancel_lesson_telebot_{lesson.id}"
            ))

        send_notification(message.chat.id, "Выберите занятие для отмены:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('cancel_lesson_telebot_'))
def process_lesson_cancel_telebot(call):
    if call.from_user.username != config.TUTOR_ID: return
    lesson_id = int(call.data.split('_')[3])
    with session_scope() as session:
        lesson = session.get(Lesson, lesson_id)
        student = session.get(Student, lesson.student_id)
        lesson.status = 'cancelled'
        lesson.report_status = 'cancelled'
        if lesson.homework:
            session.delete(lesson.homework)
        send_notification(call.message.chat.id,
                         f"❌ Занятие с {student.full_name} на {lesson.date_time.strftime('%d.%m.%Y %H:%M')} отменено.")
        send_lesson_report(lesson, student, 'cancelled')


@bot.message_handler(func=lambda message: message.text == '📅 Расписание на сегодня' or message.text == '/today')
def todays_schedule(message):
    if message.from_user.username != config.TUTOR_ID: return
    with session_scope() as session:
        today = datetime.now().date()

        lessons = session.query(Lesson).filter(
            Lesson.status == 'запланирован',
            Lesson.date_time >= datetime.combine(today, time.min),
            Lesson.date_time <= datetime.combine(today, time.max)
        ).order_by(Lesson.date_time).all()

        if not lessons:
            send_notification(message.chat.id, "На сегодня занятий нет.")
            return

        response = "📅 Занятия на сегодня:\n\n"
        for lesson in lessons:
            student = session.get(Student, lesson.student_id)
            response += f"⏰ {lesson.date_time.strftime('%H:%M')} - {student.full_name}\n"
            response += f"   [ID: {lesson.id}]\n\n"

        markup = types.InlineKeyboardMarkup()
        for lesson in lessons:
            student = session.get(Student, lesson.student_id)
            markup.add(types.InlineKeyboardButton(
                text=f"{lesson.date_time.strftime('%H:%M')} - {student.full_name}",
                callback_data=f"manage_lesson_{lesson.id}"
            ))

        send_notification(message.chat.id, response, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith('manage_lesson_'))
def manage_lesson(call):
    if call.from_user.username != config.TUTOR_ID: return
    lesson_id = int(call.data.split('_')[2])
    with session_scope() as session:
        lesson = session.get(Lesson, lesson_id)
        student = session.get(Student, lesson.student_id)

        if not lesson or not student:
            send_notification(call.message.chat.id, "Занятие или студент не найдены.")
            return

        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("✏️ Изменить время", callback_data=f"edit_time_{lesson.id}"),
            types.InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_lesson_telebot_{lesson.id}")
        )
        markup.row(types.InlineKeyboardButton("📈 Отчет о занятии", callback_data=f"report_lesson_{lesson.id}"))
        markup.row(types.InlineKeyboardButton("⬅️ Назад к расписанию", callback_data="back_to_today"))


    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=f"Управление занятием:\n\n"
             f"Студент: {student.full_name}\n"
             f"Текущее время: {lesson.date_time.strftime('%d.%m.%Y %H:%M')}\n"
             f"Статус: {lesson.status}",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_time_'))
def edit_lesson_time(call):
    if call.from_user.username != config.TUTOR_ID: return
    lesson_id = int(call.data.split('_')[2])
    msg = bot.send_message(
        call.message.chat.id,
        "Введите новое время в формате ДД.ММ.ГГГГ ЧЧ:ММ\n"
        "Пример: 25.12.2023 14:30"
    )
    bot.register_next_step_handler(msg, process_time_update, lesson_id)


def process_time_update(message, lesson_id):
    if message.from_user.username != config.TUTOR_ID: return
    try:
        new_datetime = datetime.strptime(message.text, "%d.%m.%Y %H:%M")
        with session_scope() as session:
            lesson = session.get(Lesson, lesson_id)
            if not lesson:
                send_notification(message.chat.id, "Занятие не найдено.")
                return

            old_time = lesson.date_time
            lesson.date_time = new_datetime

            student = session.get(Student, lesson.student_id)

            send_notification(
                message.chat.id,
                f"✅ Время занятия изменено:\n"
                f"Студент: {student.full_name}\n"
                f"Было: {old_time.strftime('%d.%m.%Y %H:%M')}\n"
                f"Стало: {new_datetime.strftime('%d.%m.%Y %H:%M')}"
            )

            if student.receive_notifications and student.telegram_id:
                send_notification(
                    student.telegram_id,
                    f"ℹ️ Изменено время занятия:\n"
                    f"Новое время: {new_datetime.strftime('%d.%m.%Y %H:%M')}"
                )
            parents = session.query(Parent).filter_by(student_id=student.id).all()
            for parent in parents:
                send_notification(
                    parent.telegram_id,
                    f"ℹ️ Изменено время занятия вашего ребенка {student.full_name}:\n"
                    f"Новое время: {new_datetime.strftime('%d.%m.%Y %H:%M')}"
                )

    except ValueError:
        send_notification(message.chat.id, "❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ ЧЧ:ММ")
    except Exception as e:
        send_notification(message.chat.id, f"❌ Ошибка: {str(e)}")


@bot.callback_query_handler(func=lambda call: call.data == 'back_to_today')
def back_to_today_schedule(call):
    if call.from_user.username != config.TUTOR_ID: return
    todays_schedule(call.message)


@bot.callback_query_handler(func=lambda call: call.data.startswith('report_lesson_'))
def report_lesson_command(call):
    if call.from_user.username != config.TUTOR_ID: return
    lesson_id = int(call.data.split('_')[2])
    with session_scope() as session:
        lesson = session.get(Lesson, lesson_id)
        student = session.get(Student, lesson.student_id)

        if not lesson or not student:
            send_notification(call.message.chat.id, "Занятие или студент не найдены.")
            return

        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("✅ Занятие проведено", callback_data=f"set_report_status_{lesson.id}_completed"))
        markup.row(types.InlineKeyboardButton("❌ Занятие отменено", callback_data=f"set_report_status_{lesson.id}_cancelled"))
        markup.row(types.InlineKeyboardButton("🚫 Студент не пришел", callback_data=f"set_report_status_{lesson.id}_no_show"))
        markup.row(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"manage_lesson_{lesson.id}"))

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"Отчет по занятию с {student.full_name} ({lesson.date_time.strftime('%d.%m.%Y %H:%M')}):\n\n"
                 f"Выберите статус занятия:",
            reply_markup=markup
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_report_status_'))
def set_report_status(call):
    if call.from_user.username != config.TUTOR_ID: return
    parts = call.data.split('_')
    lesson_id = int(parts[3])
    report_status = parts[4]

    with session_scope() as session:
        lesson = session.get(Lesson, lesson_id)
        student = session.get(Student, lesson.student_id)
        if not lesson or not student:
            send_notification(call.message.chat.id, "Занятие или студент не найдены.")
            return

        lesson.report_status = report_status
        lesson.status = report_status

        if report_status == 'completed':
            msg = bot.send_message(
                call.message.chat.id,
                "Введите тему занятия, ссылку на видео (если есть) и домашнее задание (если есть), разделяя запятыми.\n"
                "Пример: Введение в питон,http://video.com/lesson1,Прочитать главу 3\n"
                "Если чего-то нет, оставьте пустым: Введение в питон,,Прочитать главу 3\n"
            )
            bot.register_next_step_handler(msg, process_completed_report_details, lesson_id)
        else:
            if lesson.homework:
                session.delete(lesson.homework)

            send_notification(call.message.chat.id, f"Статус занятия обновлен: {report_status_mapping.get(report_status, report_status)}")
            send_lesson_report(lesson, student, report_status)
            todays_schedule(call.message)


report_status_mapping = {
    'completed': 'Проведено',
    'cancelled': 'Отменено',
    'no_show': 'Не пришел',
    'scheduled': 'Запланировано'
}


def process_completed_report_details(message, lesson_id):
    if message.from_user.username != config.TUTOR_ID: return
    try:
        parts = message.text.split(',')
        topic_covered = parts[0].strip() if len(parts) > 0 else None
        video_link = parts[1].strip() if len(parts) > 1 else None
        homework_description = parts[2].strip() if len(parts) > 2 else None

        msg_next_lesson = bot.send_message(
            message.chat.id,
            "Введите дату и время следующего занятия в формате ДД.ММ.ГГГГ ЧЧ:ММ (или 'нет', если не запланировано)."
        )
        bot.register_next_step_handler(msg_next_lesson, process_next_lesson_date, lesson_id, topic_covered, video_link, homework_description)

    except Exception as e:
        send_notification(message.chat.id, f"Ошибка ввода данных: {e}. Попробуйте еще раз.")
        with session_scope() as session:
            lesson = session.get(Lesson, lesson_id)
            student = session.get(Student, lesson.student_id)
            markup = types.InlineKeyboardMarkup()
            markup.row(types.InlineKeyboardButton("✅ Занятие проведено", callback_data=f"set_report_status_{lesson.id}_completed"))
            markup.row(types.InlineKeyboardButton("❌ Занятие отменено", callback_data=f"set_report_status_{lesson.id}_cancelled"))
            markup.row(types.InlineKeyboardButton("🚫 Студент не пришел", callback_data=f"set_report_status_{lesson.id}_no_show"))
            markup.row(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"manage_lesson_{lesson.id}"))

            send_notification(
                message.chat.id,
                f"Отчет по занятию с {student.full_name} ({lesson.date_time.strftime('%d.%m.%Y %H:%M')}):\n\n"
                f"Выберите статус занятия:",
                reply_markup=markup
            )


def process_next_lesson_date(message, lesson_id, topic_covered, video_link, homework_description):
    if message.from_user.username != config.TUTOR_ID: return
    next_lesson_date = None
    if message.text.lower() != 'нет':
        try:
            next_lesson_date = datetime.strptime(message.text, "%d.%m.%Y %H:%M")
        except ValueError:
            send_notification(message.chat.id, "❌ Неверный формат даты следующего занятия. Используйте ДД.ММ.ГГГГ ЧЧ:ММ или 'нет'.")
            return

    with session_scope() as session:
        lesson = session.get(Lesson, lesson_id)
        student = session.get(Student, lesson.student_id)

        lesson.topic_covered = topic_covered
        lesson.video_link = video_link
        lesson.next_lesson_date = next_lesson_date

        # --- НОВЫЙ КОД ДЛЯ ВЫЧЕТА ЗАНЯТИЙ ---
        if student.lessons_count > 0:
            student.lessons_count -= 1
            send_notification(message.chat.id, f"✅ У студента {student.full_name} снято 1 занятие. Текущий баланс: {student.lessons_count}")
        else:
            send_notification(message.chat.id, f"ВНИМАНИЕ: Занятие с {student.full_name} отмечено как завершенное, но баланс занятий студента уже 0 или меньше.")
        # --- КОНЕЦ НОВОГО КОДА ---

        if next_lesson_date:
            new_lesson = Lesson(
                student_id=lesson.student_id,
                date_time=next_lesson_date,
                status='scheduled'
            )
            session.add(new_lesson)
            if student.receive_notifications:
                send_notification(student.telegram_id, f"Новое занятие запланировано на: {new_lesson.date_time.strftime('%d.%m.%Y %H:%M')}")
                for parent in student.parents:
                    send_notification(parent.telegram_id, f"Новое занятие для {student.full_name} запланировано на: {new_lesson.date_time.strftime('%d.%m.%Y %H:%M')}")

        # Инициализируем homework_obj до условного блока
        homework_obj = None
        if homework_description:
            existing_homework = session.query(Homework).filter_by(lesson_id=lesson.id).first()
            if existing_homework:
                existing_homework.description = homework_description
                existing_homework.is_completed = False
                existing_homework.completed_date = None
                homework_obj = existing_homework
            else:
                homework_obj = Homework(
                    lesson_id=lesson.id,
                    student_id=student.id,
                    description=homework_description
                )
                session.add(homework_obj)

        send_notification(
            message.chat.id,
            f"✅ Отчет по занятию с {student.full_name} добавлен. Занятие завершено."
        )
        # Убедимся, что передаем homework_obj.description только если homework_obj существует
        send_lesson_report(lesson, student, 'completed', homework_obj.description if homework_obj else None)
        todays_schedule(message)

@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_homework_'))
def confirm_homework_callback(call):
    homework_id = int(call.data.split('_')[2])
    with session_scope() as session:
        homework = session.get(Homework, homework_id)
        if not homework:
            send_notification(call.message.chat.id, "Домашнее задание не найдено.")
            return

        if homework.is_completed:
            send_notification(call.message.chat.id, "Это домашнее задание уже было подтверждено.")
            return

        if homework.student.telegram_id != str(call.message.chat.id):
            send_notification(call.message.chat.id, "Вы не являетесь владельцем этого домашнего задания.")
            return

        homework.is_completed = True
        homework.completed_date = datetime.now()

        try:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=call.message.text + "\n\n🎉 Выполнено!"
            )
        except Exception as e:
            print(f"Не удалось обновить сообщение о ДЗ: {e}")

        send_notification(call.message.chat.id, "Отлично! Выполнение домашнего задания подтверждено.")

        with session_scope() as session_inner:
            tutor = session_inner.query(Tutor).first()
            if tutor and tutor.chat_id:
                student = session_inner.query(Student).get(homework.student_id)
                send_notification(tutor.chat_id, f"✅ Студент {student.full_name} подтвердил выполнение домашнего задания: {homework.description}")


@bot.message_handler(commands=['complete_homework'])
def complete_homework_command(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            send_notification(message.chat.id, "Используйте: /complete_homework <ID домашнего задания>")
            return
        homework_id = int(parts[1])
        with session_scope() as session:
            homework = session.get(Homework, homework_id)
            if not homework:
                send_notification(message.chat.id, "Домашнее задание с таким ID не найдено.")
                return

            if homework.is_completed:
                send_notification(message.chat.id, "Это домашнее задание уже было подтверждено.")
                return

            if homework.student.telegram_id != str(message.chat.id):
                send_notification(message.chat.id, "Вы не являетесь владельцем этого домашнего задания.")
                return

            homework.is_completed = True
            homework.completed_date = datetime.now()

            send_notification(message.chat.id, "Отлично! Выполнение домашнего задания подтверждено.")
            with session_scope() as session_inner:
                tutor = session_inner.query(Tutor).first()
                if tutor and tutor.chat_id:
                    student = session_inner.query(Student).get(homework.student_id)
                    send_notification(tutor.chat_id, f"✅ Студент {student.full_name} подтвердил выполнение домашнего задания: {homework.description}")

    except ValueError:
        send_notification(message.chat.id, "Неверный ID домашнего задания.")
    except Exception as e:
        send_notification(message.chat.id, f"Произошла ошибка: {e}")


# Маршруты для студентов
@app.route('/student_dashboard')
def student_dashboard():
    if flask_session.get('role') != 'student':
        flash('У вас нет прав для доступа к этой странице', 'error')
        return redirect(url_for('today_lessons'))
    
    student_id = flask_session.get('student_id')
    with session_scope() as session:
        lessons = session.query(Lesson).filter_by(student_id=student_id).order_by(Lesson.date_time.desc()).all()
        return render_template('student_dashboard.html', lessons=lessons)

@app.route('/student_homework')
def student_homework():
    if flask_session.get('role') != 'student':
        flash('У вас нет прав для доступа к этой странице', 'error')
        return redirect(url_for('today_lessons'))
    
    student_id = flask_session.get('student_id')
    with session_scope() as session:
        homeworks = session.query(Homework).filter_by(student_id=student_id).order_by(Homework.due_date.asc()).all()
        return render_template('student_homework.html', homeworks=homeworks)

@app.route('/submit_homework_student/<int:homework_id>', methods=['POST'])
def submit_homework_student(homework_id):
    if flask_session.get('role') != 'student':
        flash('У вас нет прав для доступа к этой странице', 'error')
        return redirect(url_for('today_lessons'))
    
    student_id = flask_session.get('student_id')
    with session_scope() as session:
        homework = session.query(Homework).filter_by(id=homework_id, student_id=student_id).first()
        if homework and not homework.submitted_date:
            homework.student_comment = request.form.get('student_comment', '').strip()
            homework.submitted_date = datetime.now()
            homework.is_completed = True  # Отмечаем как выполненное студентом
            
            # Уведомляем репетитора
            comment_text = f"\n\nКомментарий: {homework.student_comment}" if homework.student_comment else ""
            send_notification(config.TUTOR_ID, 
                f"📤 Студент {homework.student.full_name} отправил на проверку домашнее задание:\n"
                f"'{homework.description}'{comment_text}\n\n"
                f"Подтвердите выполнение в системе.")
            
            flash('Домашнее задание отправлено на проверку!', 'success')
        else:
            flash('Домашнее задание уже отправлено или не найдено', 'error')
    
    return redirect(url_for('student_homework'))

@app.route('/mark_homework_completed_student/<int:homework_id>')
def mark_homework_completed_student(homework_id):
    # Эта функция теперь не используется, но оставляем для совместимости
    return redirect(url_for('student_homework'))

# Маршруты для управления пользователями (только для администратора)
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
                students = session.query(Student).filter(~Student.id.in_(
                    session.query(User.student_id).filter(User.student_id.isnot(None))
                )).all()
                return render_template('create_user.html', students=students)
            
            if session.query(User).filter_by(email=email).first():
                flash('Пользователь с таким email уже существует', 'error')
                students = session.query(Student).filter(~Student.id.in_(
                    session.query(User.student_id).filter(User.student_id.isnot(None))
                )).all()
                return render_template('create_user.html', students=students)
            
            # Создаем пользователя
            user = User(username=username, email=email, role=role, student_id=student_id)
            user.set_password(password)
            session.add(user)
            session.commit()
            
            flash('Пользователь успешно создан!', 'success')
            return redirect(url_for('manage_users'))
    
    with session_scope() as session:
        # Получаем студентов, у которых еще нет аккаунта
        students = session.query(Student).filter(~Student.id.in_(
            session.query(User.student_id).filter(User.student_id.isnot(None))
        )).all()
        return render_template('create_user.html', students=students)

@app.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
@role_required('admin')
def edit_user(user_id):
    with session_scope() as session:
        user = session.get(User, user_id)
        if not user:
            flash('Пользователь не найден', 'error')
            return redirect(url_for('manage_users'))
        
        if request.method == 'POST':
            username = request.form['username']
            email = request.form['email']
            role = request.form['role']
            student_id = request.form.get('student_id') if role == 'student' else None
            new_password = request.form.get('new_password')
            
            # Проверяем уникальность (исключая текущего пользователя)
            existing_user = session.query(User).filter_by(username=username).filter(User.id != user_id).first()
            if existing_user:
                flash('Пользователь с таким логином уже существует', 'error')
                students = session.query(Student).filter(~Student.id.in_(
                    session.query(User.student_id).filter(User.student_id.isnot(None), User.id != user_id)
                )).all()
                return render_template('edit_user.html', user=user, students=students)
            
            existing_user = session.query(User).filter_by(email=email).filter(User.id != user_id).first()
            if existing_user:
                flash('Пользователь с таким email уже существует', 'error')
                students = session.query(Student).filter(~Student.id.in_(
                    session.query(User.student_id).filter(User.student_id.isnot(None), User.id != user_id)
                )).all()
                return render_template('edit_user.html', user=user, students=students)
            
            # Обновляем данные
            user.username = username
            user.email = email
            user.role = role
            user.student_id = student_id
            
            if new_password:
                user.set_password(new_password)
            
            session.commit()
            flash('Пользователь успешно обновлен!', 'success')
            return redirect(url_for('manage_users'))
        
        students = session.query(Student).filter(~Student.id.in_(
            session.query(User.student_id).filter(User.student_id.isnot(None), User.id != user_id)
        )).all()
        return render_template('edit_user.html', user=user, students=students)

@app.route('/toggle_user_status/<int:user_id>')
@role_required('admin')
def toggle_user_status(user_id):
    with session_scope() as session:
        user = session.get(User, user_id)
        if user and user.role != 'admin':  # Нельзя блокировать администраторов
            user.is_active = not user.is_active
            session.commit()
            status = 'разблокирован' if user.is_active else 'заблокирован'
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
            session.delete(user)
            session.commit()
            flash(f'Пользователь {user.username} удален', 'success')
        else:
            flash('Нельзя удалить администратора', 'error')
    return redirect(url_for('manage_users'))

# Маршруты для приглашений
@app.route('/invite_student/<int:student_id>')
@role_required('admin', 'tutor')
def invite_student(student_id):
    with session_scope() as session:
        student = session.get(Student, student_id)
        if not student:
            flash('Студент не найден', 'error')
            return redirect(url_for('all_students'))
        
        # Проверяем, есть ли уже аккаунт у студента
        if student.user_account:
            flash('У этого студента уже есть аккаунт', 'error')
            return redirect(url_for('all_students'))
        
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

# Функция для создания администратора по умолчанию
def create_default_admin():
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

def run_bot():
    bot.polling(none_stop=True)

if __name__ == '__main__':
    create_default_admin()  # Создаем администратора при первом запуске
    Thread(target=run_bot).start()
    Thread(target=reminder_loop).start()
    app.run(debug=True)