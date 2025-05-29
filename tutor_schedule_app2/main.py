from flask import Flask, render_template, request, redirect, session as flask_session, url_for
from threading import Thread
from database import Session, Student, Lesson, Tutor, Parent, Homework, Payment
import config
import telebot
from telebot import types
from datetime import datetime, timedelta, time
import time # <--- НОВЫЙ ИМПОРТ: добавляем import time
from contextlib import contextmanager
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import or_ # Для поиска

app = Flask(__name__)
app.secret_key = 'secret_key'

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

@app.before_request
def require_login():
    allowed = ['login', 'static']
    if not flask_session.get('logged_in') and request.endpoint not in allowed:
        return redirect('/login')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['username'] == 'admin' and request.form['password'] == 'admin123':
            flask_session['logged_in'] = True
            return redirect('/')
        return "Неверные данные"
    return '''
        <form method="post">
        Логин: <input name="username"><br>
        Пароль: <input name="password" type="password"><br>
        <input type="submit" value="Войти">
        </form>
    '''

@app.route('/')
def index():
    with session_scope() as session:
        return redirect(url_for('today_lessons'))

@app.route('/add_student', methods=['GET', 'POST'])
def add_student():
    if request.method == 'POST':
        with session_scope() as session:
            student = Student(
                full_name=request.form['full_name'],
                lessons_count=int(request.form['lessons_count']),
                telegram_id=request.form['telegram_id'],
                receive_notifications=True
            )
            session.add(student)
        return redirect('/students')
    return render_template('add_student.html')

@app.route('/add_lesson', methods=['GET', 'POST'])
def add_lesson():
    with session_scope() as session:
        students = session.query(Student).all()
        if request.method == 'POST':
            student_id = int(request.form['student_id'])
            date_time = datetime.strptime(request.form['date_time'], "%Y-%m-%dT%H:%M")
            lesson = Lesson(student_id=student_id, date_time=date_time)
            session.add(lesson)
            student = session.query(Student).get(student_id)
            if student.receive_notifications:
                send_reminder(student, date_time, 'lesson_scheduled')
            return redirect('/all_lessons')
        return render_template('add_lesson.html', students=students)

@app.route('/delete_student/<int:student_id>')
def delete_student(student_id):
    with session_scope() as session:
        student = session.query(Student).get(student_id)
        if student:
            session.delete(student)
        return redirect('/students')

@app.route('/student/<int:student_id>/add_parent', methods=['GET', 'POST'])
def add_parent(student_id):
    with session_scope() as session:
        student = session.query(Student).get(student_id)
        if not student:
            return "Student not found", 404

        if request.method == 'POST':
            telegram_id = request.form['telegram_id'].strip()
            if telegram_id:
                existing_parent = session.query(Parent).filter_by(student_id=student.id, telegram_id=telegram_id).first()
                if not existing_parent:
                    parent = Parent(student_id=student.id, telegram_id=telegram_id)
                    session.add(parent)
                    if student.receive_notifications and student.telegram_id:
                        send_notification(student.telegram_id, f"Поздравляем! Ваш родитель добавлен в систему: {telegram_id}. Теперь он будет получать уведомления о ваших занятиях.")
                    send_notification(telegram_id, f"Вы добавлены как родитель студента {student.full_name}. Вы будете получать уведомления о его занятиях.")
                    return redirect(url_for('view_student_card', student_id=student_id))
                else:
                    return "Родитель с таким Telegram ID уже привязан к этому студенту.", 409
            return "Telegram ID не может быть пустым.", 400
        return render_template('add_parent.html', student=student)

@app.route('/student/<int:student_id>/delete_parent/<int:parent_id>')
def delete_parent(student_id, parent_id):
    with session_scope() as session:
        parent = session.query(Parent).get(parent_id)
        if parent and parent.student_id == student_id:
            student = parent.student
            session.delete(parent)
            send_notification(parent.telegram_id, f"Вы удалены из списка родителей студента {student.full_name}.")
            if student.receive_notifications and student.telegram_id:
                send_notification(student.telegram_id, f"Ваш родитель с Telegram ID {parent.telegram_id} был удален из системы.")
        return redirect(url_for('view_student_card', student_id=student_id))

@app.route('/student/<int:student_id>/add_payment', methods=['GET', 'POST'])
def add_payment(student_id):
    with session_scope() as session:
        student = session.query(Student).get(student_id)
        if not student:
            return "Student not found", 404

        if request.method == 'POST':
            try:
                amount = float(request.form['amount'])
                description = request.form['description']
                payment = Payment(student_id=student.id, amount=amount, description=description)
                session.add(payment)
                if student.receive_notifications and student.telegram_id:
                    send_notification(student.telegram_id, f"✅ Платеж на сумму {amount} руб. от вас или вашего родителя зачислен на счет {student.full_name}. ({description or 'Без описания'})")
                for parent in student.parents:
                    send_notification(parent.telegram_id, f"✅ Платеж на сумму {amount} руб. за студента {student.full_name} зачислен. ({description or 'Без описания'})")
                return redirect(url_for('view_student_card', student_id=student_id))
            except ValueError:
                return "Неверный формат суммы.", 400
        return render_template('add_payment.html', student=student)

@app.route('/delete_payment/<int:payment_id>')
def delete_payment(payment_id):
    with session_scope() as session:
        payment = session.query(Payment).get(payment_id)
        if payment:
            student_id = payment.student_id
            session.delete(payment)
        return redirect(url_for('view_student_card', student_id=student_id))

@app.route('/edit_student_lessons_count/<int:student_id>', methods=['POST'])
def edit_student_lessons_count(student_id):
    with session_scope() as session:
        student = session.query(Student).get(student_id)
        if not student:
            return "Student not found", 404

        try:
            new_lessons_count = int(request.form['lessons_count'])
            student.lessons_count = new_lessons_count
            return redirect(url_for('view_student_card', student_id=student_id))
        except ValueError:
            return "Неверное количество занятий.", 400

@app.route('/toggle_student_notifications/<int:student_id>', methods=['POST'])
def toggle_student_notifications(student_id):
    with session_scope() as session:
        student = session.query(Student).get(student_id)
        if not student:
            return "Student not found", 404

        student.receive_notifications = not student.receive_notifications

        status = "включены" if student.receive_notifications else "отключены"
        send_tutor_notification(f"Уведомления для студента {student.full_name} теперь {status}.")
        if student.telegram_id:
            send_notification(student.telegram_id, f"Ваши уведомления теперь {status}.")

        return redirect(url_for('view_student_card', student_id=student_id))


@app.route('/student/<int:student_id>')
def view_student_card(student_id):
    with session_scope() as session:
        student = session.query(Student).get(student_id)
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
def all_students():
    with session_scope() as session:
        search_query = request.args.get('search', '').strip()
        if search_query:
            students = session.query(Student).filter(
                or_(
                    Student.full_name.ilike(f'%{search_query}%'),
                    Student.telegram_id.ilike(f'%{search_query}%')
                )
            ).all()
        else:
            students = session.query(Student).all()
        return render_template('all_students.html', students=students, search_query=search_query)

@app.route('/all_lessons')
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
            Lesson.status == 'scheduled'
        ).order_by(Lesson.date_time).all()

        return render_template('today_lessons.html', lessons=lessons, today=today.strftime('%d.%m.%Y'))

@app.route('/edit_lesson/<int:lesson_id>', methods=['GET', 'POST'])
def edit_lesson(lesson_id):
    with session_scope() as session:
        lesson = session.query(Lesson).get(lesson_id)
        student = session.query(Student).get(lesson.student_id)

        if not lesson or not student:
            return "Занятие или студент не найдены", 404

        if request.method == 'POST':
            try:
                new_datetime_str = request.form.get('date_time')
                if new_datetime_str:
                    lesson.date_time = datetime.strptime(new_datetime_str, "%Y-%m-%dT%H:%M")

                report_status = request.form.get('report_status')
                lesson.report_status = report_status
                lesson.status = report_status

                lesson.topic_covered = request.form.get('topic_covered')
                lesson.video_link = request.form.get('video_link')
                homework_description = request.form.get('homework_description')

                next_lesson_date_str = request.form.get('next_lesson_date')
                if next_lesson_date_str:
                    lesson.next_lesson_date = datetime.strptime(next_lesson_date_str, "%Y-%m-%dT%H:%M")
                else:
                    lesson.next_lesson_date = None

                if report_status == 'completed' and lesson.next_lesson_date:
                    new_lesson = Lesson(
                        student_id=lesson.student_id,
                        date_time=lesson.next_lesson_date,
                        status='scheduled'
                    )
                    session.add(new_lesson)
                    if student.receive_notifications:
                        send_notification(student.telegram_id, f"Новое занятие запланировано на: {new_lesson.date_time.strftime('%d.%m.%Y %H:%M')}")
                        for parent in student.parents:
                            send_notification(parent.telegram_id, f"Новое занятие для {student.full_name} запланировано на: {new_lesson.date_time.strftime('%d.%m.%Y %H:%M')}")


                if report_status == 'completed' and homework_description:
                    existing_homework = session.query(Homework).filter_by(lesson_id=lesson.id).first()
                    if existing_homework:
                        existing_homework.description = homework_description
                        existing_homework.is_completed = False
                        existing_homework.completed_date = None
                    else:
                        homework = Homework(
                            lesson_id=lesson.id,
                            student_id=student.id,
                            description=homework_description
                        )
                        session.add(homework)
                elif report_status != 'completed' and lesson.homework:
                    session.delete(lesson.homework)

                send_lesson_report(lesson, student, report_status, homework_description)

                return redirect(url_for('today_lessons'))
            except ValueError:
                return "Неверный формат даты/времени", 400

        return render_template('edit_lesson.html',
                               lesson=lesson,
                               student=student,
                               current_time=lesson.date_time.strftime('%Y-%m-%dT%H:%M'))


@app.route('/cancel_lesson_web/<int:lesson_id>')
def cancel_lesson_web(lesson_id):
    with session_scope() as session:
        lesson = session.query(Lesson).get(lesson_id)
        student = session.query(Student).get(lesson.student_id)
        lesson.status = 'cancelled'
        lesson.report_status = 'cancelled'
        if lesson.homework:
            session.delete(lesson.homework)
        send_lesson_report(lesson, student, 'cancelled')
        return redirect(url_for('today_lessons'))

@app.route('/mark_homework_completed_web/<int:homework_id>')
def mark_homework_completed_web(homework_id):
    with session_scope() as session:
        homework = session.query(Homework).get(homework_id)
        if homework:
            homework.is_completed = True
            homework.completed_date = datetime.now()
            tutor = session.query(Tutor).first()
            if tutor and tutor.chat_id:
                student = session.query(Student).get(homework.student_id)
                send_notification(tutor.chat_id, f"✅ Студент {student.full_name} подтвердил выполнение домашнего задания (через веб-интерфейс): {homework.description}")
        return redirect(url_for('view_student_card', student_id=homework.student_id))


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
        student = s.query(Student).filter_by(telegram_id=str(chat_id)).first()
        if student:
            is_student_or_parent = True
            if not student.receive_notifications:
                print(f"Уведомления для студента {student.full_name} (ID: {chat_id}) отключены. Сообщение не отправлено.")
                return

        if not student:
            parent = s.query(Parent).filter_by(telegram_id=str(chat_id)).first()
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

    if student.telegram_id:
        send_notification(student.telegram_id, message_text)

    with session_scope() as session:
        parents = session.query(Parent).filter_by(student_id=student.id).all()
        for parent in parents:
            send_notification(parent.telegram_id, message_text)

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

    if student.receive_notifications and student.telegram_id and message_to_student:
        markup = None
        if homework_description:
            homework_obj = None
            with session_scope() as session_inner:
                homework_obj = session_inner.query(Homework).filter_by(lesson_id=lesson.id).first()
            if homework_obj:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("✅ Подтвердить выполнение ДЗ", callback_data=f"confirm_homework_{homework_obj.id}"))
        sent_message = send_notification(student.telegram_id, message_to_student, markup)
        if sent_message and homework_obj:
             with session_scope() as session_inner:
                hw_to_update = session_inner.query(Homework).get(homework_obj.id)
                if hw_to_update:
                    hw_to_update.telegram_message_id = str(sent_message.message_id)


    with session_scope() as session_inner:
        parents = session_inner.query(Parent).filter_by(student_id=student.id).all()
        if message_to_parents:
            for parent in parents:
                send_notification(parent.telegram_id, message_to_parents)


def reminder_loop():
    while True:
        with session_scope() as session:
            tutor = session.query(Tutor).first()
            now = datetime.now()

            # --- Reminders for Lessons ---
            upcoming_lessons = session.query(Lesson).filter(
                Lesson.status == 'scheduled',
                Lesson.date_time > now
            ).all()

            for lesson in upcoming_lessons:
                student = session.query(Student).get(lesson.student_id)
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
                Lesson.status == 'scheduled',
                Homework.is_completed == False,
                Lesson.date_time > now,
                (Lesson.date_time - now) < timedelta(hours=6)
            ).all()

            for lesson in lessons_with_homework_due:
                homework = lesson.homework
                student = session.query(Student).get(lesson.student_id)
                if student and student.telegram_id and student.receive_notifications:
                    send_notification(student.telegram_id,
                                      f"⏰ Напоминание: Домашнее задание к занятию с {student.full_name} в {lesson.date_time.strftime('%H:%M')} еще не сдано.\n"
                                      f"Задание: {homework.description}\n"
                                      f"Пожалуйста, подтвердите выполнение кнопкой под сообщением с ДЗ, или отправьте '/complete_homework_{homework.id}'")

        time.sleep(60)


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
            student = session.query(Student).get(lesson.student_id)
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

            student = session.query(Student).get(student_id)
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
            student = session.query(Student).get(lesson.student_id)
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
        lesson = session.query(Lesson).get(lesson_id)
        student = session.query(Student).get(lesson.student_id)
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
            Lesson.status == 'scheduled',
            Lesson.date_time >= datetime.combine(today, time.min),
            Lesson.date_time <= datetime.combine(today, time.max)
        ).order_by(Lesson.date_time).all()

        if not lessons:
            send_notification(message.chat.id, "На сегодня занятий нет.")
            return

        response = "📅 Занятия на сегодня:\n\n"
        for lesson in lessons:
            student = session.query(Student).get(lesson.student_id)
            response += f"⏰ {lesson.date_time.strftime('%H:%M')} - {student.full_name}\n"
            response += f"   [ID: {lesson.id}]\n\n"

        markup = types.InlineKeyboardMarkup()
        for lesson in lessons:
            student = session.query(Student).get(lesson.student_id)
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
        lesson = session.query(Lesson).get(lesson_id)
        student = session.query(Student).get(lesson.student_id)

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
            lesson = session.query(Lesson).get(lesson_id)
            if not lesson:
                send_notification(message.chat.id, "Занятие не найдено.")
                return

            old_time = lesson.date_time
            lesson.date_time = new_datetime

            student = session.query(Student).get(lesson.student_id)

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
        lesson = session.query(Lesson).get(lesson_id)
        student = session.query(Student).get(lesson.student_id)

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
        lesson = session.query(Lesson).get(lesson_id)
        student = session.query(Student).get(lesson.student_id)
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
            lesson = session.query(Lesson).get(lesson_id)
            student = session.query(Student).get(lesson.student_id)
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
        lesson = session.query(Lesson).get(lesson_id)
        student = session.query(Student).get(lesson.student_id)

        lesson.topic_covered = topic_covered
        lesson.video_link = video_link
        lesson.next_lesson_date = next_lesson_date

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
        send_lesson_report(lesson, student, 'completed', homework_obj.description if homework_obj else None)
        todays_schedule(message)

@bot.callback_query_handler(func=lambda call: call.data.startswith('confirm_homework_'))
def confirm_homework_callback(call):
    homework_id = int(call.data.split('_')[2])
    with session_scope() as session:
        homework = session.query(Homework).get(homework_id)
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
            homework = session.query(Homework).get(homework_id)
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


def run_bot():
    bot.polling(none_stop=True)

if __name__ == '__main__':
    Thread(target=run_bot).start()
    Thread(target=reminder_loop).start()
    app.run(debug=True)