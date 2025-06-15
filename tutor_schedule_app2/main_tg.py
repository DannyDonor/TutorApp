import telebot
from telebot import types
from database import Session, Student, Lesson, Tutor, Parent, Homework, Payment, User, Invitation
import config
from datetime import datetime, timedelta
from contextlib import contextmanager
from sqlalchemy.exc import SQLAlchemyError
import secrets
import time
from threading import Thread

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

def send_notification(chat_id, message, reply_markup=None):
    """Отправка уведомления с обработкой ошибок"""
    try:
        bot.send_message(chat_id, message, reply_markup=reply_markup, parse_mode='HTML')
    except Exception as e:
        print(f"Ошибка отправки уведомления в чат {chat_id}: {e}")

def send_student_invitation(student_id, email):
    """Отправка приглашения студенту для создания аккаунта"""
    with session_scope() as session:
        # Создаем приглашение
        invitation = Invitation(
            email=email,
            role='student',
            student_id=student_id,
            created_by=1,  # Предполагаем, что создает админ
            expires_at=datetime.now() + timedelta(days=7)
        )
        invitation.generate_token()
        session.add(invitation)
        session.commit()
        
        # Здесь можно добавить отправку email с ссылкой на регистрацию
        print(f"Приглашение создано для студента {student_id}: {invitation.token}")

# ================== ОБРАБОТЧИКИ ДЛЯ СТУДЕНТОВ ==================

@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = str(message.chat.id)
    
    # Проверяем, репетитор ли это
    if message.from_user.username == config.TUTOR_ID:
        with session_scope() as session:
            existing_tutor = session.query(Tutor).filter_by(chat_id=chat_id).first()
            if not existing_tutor:
                tutor = Tutor(chat_id=chat_id)
                session.add(tutor)
        send_tutor_menu(message.chat.id)
        return
    
    # Проверяем, студент ли это
    with session_scope() as session:
        student = session.query(Student).filter_by(telegram_chat_id=chat_id).first()
        if student:
            if student.receive_notifications:
                send_student_menu(message.chat.id, student)
            else:
                send_notification(message.chat.id, "Добро пожаловать! Ваши уведомления отключены. Чтобы их включить, обратитесь к репетитору.")
        else:
            send_notification(message.chat.id, "Добро пожаловать! Для начала работы попросите вашего репетитора добавить вас в систему.")

def send_student_menu(chat_id, student=None):
    """Отправка главного меню для студента"""
    if not student:
        with session_scope() as session:
            student = session.query(Student).filter_by(telegram_chat_id=str(chat_id)).first()
    
    if not student:
        send_notification(chat_id, "Вы не зарегистрированы в системе. Обратитесь к репетитору.")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    # Основные кнопки
    btn_lessons = types.InlineKeyboardButton("📚 Мои уроки", callback_data=f"student_lessons_{student.id}")
    btn_homework = types.InlineKeyboardButton("📝 Домашние задания", callback_data=f"student_homework_{student.id}")
    btn_schedule = types.InlineKeyboardButton("📅 Расписание", callback_data=f"student_schedule_{student.id}")
    btn_progress = types.InlineKeyboardButton("📊 Мой прогресс", callback_data=f"student_progress_{student.id}")
    
    markup.add(btn_lessons, btn_homework)
    markup.add(btn_schedule, btn_progress)
    
    # Дополнительные кнопки
    btn_notifications = types.InlineKeyboardButton("🔔 Уведомления", callback_data=f"student_notifications_{student.id}")
    btn_help = types.InlineKeyboardButton("❓ Помощь", callback_data="student_help")
    
    markup.add(btn_notifications, btn_help)
    
    welcome_text = f"👋 Добро пожаловать, {student.full_name}!\n\n"
    welcome_text += "Выберите нужный раздел:"
    
    send_notification(chat_id, welcome_text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('student_lessons_'))
def handle_student_lessons(call):
    student_id = int(call.data.split('_')[2])
    
    with session_scope() as session:
        student = session.query(Student).get(student_id)
        if not student or student.telegram_chat_id != str(call.message.chat.id):
            bot.answer_callback_query(call.id, "Ошибка доступа")
            return
        
        # Получаем последние уроки студента
        lessons = session.query(Lesson).filter_by(student_id=student_id).order_by(Lesson.date_time.desc()).limit(10).all()
        
        if not lessons:
            text = "📚 У вас пока нет уроков."
        else:
            text = f"📚 Ваши уроки:\n\n"
            for lesson in lessons:
                status_emoji = {
                    'запланирован': '🕐',
                    'проведен': '✅',
                    'отменен': '❌',
                    'не_пришел': '🚫'
                }.get(lesson.status, '❓')
                
                date_str = lesson.date_time.strftime('%d.%m.%Y %H:%M')
                text += f"{status_emoji} {date_str} - {lesson.status}\n"
                if lesson.topic_covered:
                    text += f"   📖 Тема: {lesson.topic_covered}\n"
                if lesson.video_link:
                    text += f"   🎥 Видео: {lesson.video_link}\n"
                text += "\n"
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data=f"student_menu_{student_id}"))
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('student_homework_'))
def handle_student_homework(call):
    student_id = int(call.data.split('_')[2])
    
    with session_scope() as session:
        student = session.query(Student).get(student_id)
        if not student or student.telegram_chat_id != str(call.message.chat.id):
            bot.answer_callback_query(call.id, "Ошибка доступа")
            return
        
        # Получаем домашние задания
        homeworks = session.query(Homework).filter_by(student_id=student_id).order_by(Homework.due_date.asc()).all()
        
        if not homeworks:
            text = "📝 У вас нет домашних заданий."
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data=f"student_menu_{student_id}"))
        else:
            text = f"📝 Ваши домашние задания:\n\n"
            markup = types.InlineKeyboardMarkup(row_width=1)
            
            for hw in homeworks:
                if hw.is_confirmed_by_tutor:
                    status = "✅ Проверено"
                elif hw.submitted_date:
                    status = "⏳ На проверке"
                else:
                    status = "❌ Не выполнено"
                
                due_date = hw.due_date.strftime('%d.%m.%Y') if hw.due_date else "Без срока"
                text += f"{status} | {due_date}\n"
                text += f"📋 {hw.description}\n"
                
                if hw.student_comment:
                    text += f"💬 Ваш комментарий: {hw.student_comment}\n"
                
                # Кнопки для действий с домашним заданием
                if not hw.submitted_date:
                    markup.add(types.InlineKeyboardButton(
                        f"📤 Сдать: {hw.description[:30]}...", 
                        callback_data=f"submit_hw_{hw.id}"
                    ))
                
                text += "\n"
            
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data=f"student_menu_{student_id}"))
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('submit_hw_'))
def handle_submit_homework(call):
    homework_id = int(call.data.split('_')[2])
    
    with session_scope() as session:
        homework = session.query(Homework).get(homework_id)
        if not homework or homework.student.telegram_chat_id != str(call.message.chat.id):
            bot.answer_callback_query(call.id, "Ошибка доступа")
            return
        
        if homework.submitted_date:
            bot.answer_callback_query(call.id, "Это задание уже отправлено на проверку")
            return
        
        text = f"📝 Отправка домашнего задания:\n\n"
        text += f"📋 Задание: {homework.description}\n\n"
        text += "Напишите комментарий к выполненному заданию или отправьте /skip для отправки без комментария:"
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data=f"student_homework_{homework.student_id}"))
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
        
        # Устанавливаем режим ожидания комментария
        bot.register_next_step_handler(call.message, process_homework_comment, homework_id)

def process_homework_comment(message, homework_id):
    """Обработка комментария к домашнему заданию"""
    if message.text == '/skip':
        comment = ""
    else:
        comment = message.text
    
    with session_scope() as session:
        homework = session.query(Homework).get(homework_id)
        if homework and homework.student.telegram_chat_id == str(message.chat.id):
            homework.student_comment = comment
            homework.submitted_date = datetime.now()
            homework.is_completed = True
            
            # Уведомляем репетитора
            comment_text = f"\n\nКомментарий: {comment}" if comment else ""
            send_notification(config.TUTOR_ID, 
                f"📤 Студент {homework.student.full_name} отправил на проверку домашнее задание:\n"
                f"'{homework.description}'{comment_text}\n\n"
                f"Подтвердите выполнение в системе.")
            
            send_notification(message.chat.id, "✅ Домашнее задание отправлено на проверку!")
            
            # Возвращаемся в меню домашних заданий
            send_student_menu(message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('student_schedule_'))
def handle_student_schedule(call):
    student_id = int(call.data.split('_')[2])
    
    with session_scope() as session:
        student = session.query(Student).get(student_id)
        if not student or student.telegram_chat_id != str(call.message.chat.id):
            bot.answer_callback_query(call.id, "Ошибка доступа")
            return
        
        # Получаем ближайшие уроки
        now = datetime.now()
        upcoming_lessons = session.query(Lesson).filter(
            Lesson.student_id == student_id,
            Lesson.date_time > now,
            Lesson.status == 'запланирован'
        ).order_by(Lesson.date_time.asc()).limit(10).all()
        
        if not upcoming_lessons:
            text = "📅 У вас нет запланированных уроков."
        else:
            text = f"📅 Ваше расписание:\n\n"
            for lesson in upcoming_lessons:
                date_str = lesson.date_time.strftime('%d.%m.%Y %H:%M')
                days_until = (lesson.date_time.date() - now.date()).days
                
                if days_until == 0:
                    time_info = "сегодня"
                elif days_until == 1:
                    time_info = "завтра"
                else:
                    time_info = f"через {days_until} дн."
                
                text += f"📚 {date_str} ({time_info})\n"
                if lesson.next_lesson_date:
                    next_date = lesson.next_lesson_date.strftime('%d.%m.%Y %H:%M')
                    text += f"   ➡️ Следующий урок: {next_date}\n"
                text += "\n"
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data=f"student_menu_{student_id}"))
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('student_progress_'))
def handle_student_progress(call):
    student_id = int(call.data.split('_')[2])
    
    with session_scope() as session:
        student = session.query(Student).get(student_id)
        if not student or student.telegram_chat_id != str(call.message.chat.id):
            bot.answer_callback_query(call.id, "Ошибка доступа")
            return
        
        # Статистика уроков
        total_lessons = session.query(Lesson).filter_by(student_id=student_id).count()
        completed_lessons = session.query(Lesson).filter_by(student_id=student_id, status='проведен').count()
        missed_lessons = session.query(Lesson).filter_by(student_id=student_id, status='не_пришел').count()
        
        # Статистика домашних заданий
        total_homeworks = session.query(Homework).filter_by(student_id=student_id).count()
        completed_homeworks = session.query(Homework).filter_by(student_id=student_id, is_confirmed_by_tutor=True).count()
        pending_homeworks = session.query(Homework).filter(
            Homework.student_id == student_id,
            Homework.submitted_date.isnot(None),
            Homework.is_confirmed_by_tutor == False
        ).count()
        
        # Последние платежи
        recent_payments = session.query(Payment).filter_by(student_id=student_id).order_by(Payment.payment_date.desc()).limit(3).all()
        
        text = f"📊 Ваш прогресс:\n\n"
        text += f"📚 Уроки:\n"
        text += f"   • Всего: {total_lessons}\n"
        text += f"   • Проведено: {completed_lessons}\n"
        text += f"   • Пропущено: {missed_lessons}\n\n"
        
        text += f"📝 Домашние задания:\n"
        text += f"   • Всего: {total_homeworks}\n"
        text += f"   • Выполнено: {completed_homeworks}\n"
        text += f"   • На проверке: {pending_homeworks}\n\n"
        
        if recent_payments:
            text += f"💰 Последние платежи:\n"
            for payment in recent_payments:
                date_str = payment.payment_date.strftime('%d.%m.%Y')
                text += f"   • {date_str}: {payment.amount} руб.\n"
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data=f"student_menu_{student_id}"))
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('student_notifications_'))
def handle_student_notifications(call):
    student_id = int(call.data.split('_')[2])
    
    with session_scope() as session:
        student = session.query(Student).get(student_id)
        if not student or student.telegram_chat_id != str(call.message.chat.id):
            bot.answer_callback_query(call.id, "Ошибка доступа")
            return
        
        current_status = "включены" if student.receive_notifications else "отключены"
        
        text = f"🔔 Уведомления сейчас {current_status}.\n\n"
        text += "Вы получаете уведомления о:\n"
        text += "• Новых уроках\n"
        text += "• Напоминаниях о занятиях\n"
        text += "• Домашних заданиях\n"
        text += "• Изменениях в расписании\n\n"
        text += "Что хотите сделать?"
        
        markup = types.InlineKeyboardMarkup()
        if student.receive_notifications:
            markup.add(types.InlineKeyboardButton("🔕 Отключить уведомления", callback_data=f"toggle_notifications_{student_id}"))
        else:
            markup.add(types.InlineKeyboardButton("🔔 Включить уведомления", callback_data=f"toggle_notifications_{student_id}"))
        
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data=f"student_menu_{student_id}"))
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('toggle_notifications_'))
def handle_toggle_notifications(call):
    student_id = int(call.data.split('_')[2])
    
    with session_scope() as session:
        student = session.query(Student).get(student_id)
        if not student or student.telegram_chat_id != str(call.message.chat.id):
            bot.answer_callback_query(call.id, "Ошибка доступа")
            return
        
        student.receive_notifications = not student.receive_notifications
        session.commit()
        
        status = "включены" if student.receive_notifications else "отключены"
        bot.answer_callback_query(call.id, f"Уведомления {status}")
        
        # Обновляем сообщение
        handle_student_notifications(call)

@bot.callback_query_handler(func=lambda call: call.data == 'student_help')
def handle_student_help(call):
    text = """❓ Помощь по использованию бота:

📚 <b>Мои уроки</b> - просмотр истории занятий
📝 <b>Домашние задания</b> - список заданий и их статус
📅 <b>Расписание</b> - ближайшие запланированные уроки
📊 <b>Мой прогресс</b> - статистика по урокам и заданиям
🔔 <b>Уведомления</b> - настройка уведомлений

<b>Команды:</b>
/start - главное меню
/menu - вернуться в меню

<b>Как сдать домашнее задание:</b>
1. Выберите "Домашние задания"
2. Нажмите "Сдать" у нужного задания
3. Напишите комментарий или /skip
4. Задание будет отправлено на проверку

По вопросам обращайтесь к вашему репетитору."""
    
    markup = types.InlineKeyboardMarkup()
    
    # Определяем student_id из предыдущих сообщений
    with session_scope() as session:
        student = session.query(Student).filter_by(telegram_chat_id=str(call.message.chat.id)).first()
        if student:
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data=f"student_menu_{student.id}"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data.startswith('student_menu_'))
def handle_student_menu(call):
    student_id = int(call.data.split('_')[2])
    
    with session_scope() as session:
        student = session.query(Student).get(student_id)
        if student and student.telegram_chat_id == str(call.message.chat.id):
            # Удаляем старое сообщение и отправляем новое меню
            bot.delete_message(call.message.chat.id, call.message.message_id)
            send_student_menu(call.message.chat.id, student)

# ================== ОБРАБОТЧИКИ ДЛЯ РЕПЕТИТОРОВ ==================

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
    chat_id = str(message.chat.id)
    
    # Проверяем, репетитор ли это
    if message.from_user.username == config.TUTOR_ID:
        send_tutor_menu(message.chat.id)
    else:
        # Проверяем, студент ли это
        with session_scope() as session:
            student = session.query(Student).filter_by(telegram_chat_id=chat_id).first()
            if student:
                send_student_menu(message.chat.id, student)
            else:
                send_notification(message.chat.id, "У вас нет доступа к меню. Обратитесь к репетитору.")

# ================== ДОПОЛНИТЕЛЬНЫЕ ОБРАБОТЧИКИ ДЛЯ РЕПЕТИТОРОВ ==================

@bot.message_handler(func=lambda message: message.text == '📝 Список студентов')
def list_students_telebot(message):
    if message.from_user.username != config.TUTOR_ID:
        send_notification(message.chat.id, "У вас нет доступа к этой функции.")
        return
    
    with session_scope() as session:
        students = session.query(Student).filter_by(is_archived=False).order_by(Student.full_name).all()
        
        if not students:
            send_notification(message.chat.id, "Список студентов пуст.")
            return
        
        text = "📝 Список студентов:\n\n"
        for student in students:
            notification_status = "🔔" if student.receive_notifications else "🔕"
            text += f"{notification_status} {student.full_name}\n"
            text += f"   ID: {student.id}\n"
            text += f"   Telegram: {student.telegram_chat_id or 'не указан'}\n"
            text += f"   Уроков: {student.lessons_count}\n\n"
        
        send_notification(message.chat.id, text)

@bot.message_handler(func=lambda message: message.text == '➕ Добавить студента')
def add_student_telebot(message):
    if message.from_user.username != config.TUTOR_ID:
        send_notification(message.chat.id, "У вас нет доступа к этой функции.")
        return
    
    send_notification(message.chat.id, "Введите данные студента в формате:\nИмя Фамилия | Количество уроков | Telegram ID (или 0)")
    bot.register_next_step_handler(message, process_add_student)

def process_add_student(message):
    try:
        parts = message.text.split('|')
        if len(parts) != 3:
            send_notification(message.chat.id, "Неверный формат. Используйте: Имя Фамилия | Количество уроков | Telegram ID")
            return
        
        full_name = parts[0].strip()
        lessons_count = int(parts[1].strip())
        telegram_id = parts[2].strip()
        
        if telegram_id == '0':
            telegram_id = None
        
        with session_scope() as session:
            student = Student(
                full_name=full_name,
                lessons_count=lessons_count,
                telegram_chat_id=telegram_id,
                receive_notifications=True
            )
            session.add(student)
            session.commit()
            
            send_notification(message.chat.id, f"✅ Студент {full_name} добавлен!")
    
    except ValueError:
        send_notification(message.chat.id, "Ошибка: количество уроков должно быть числом")
    except Exception as e:
        send_notification(message.chat.id, f"Ошибка добавления студента: {e}")

@bot.message_handler(func=lambda message: message.text == '📅 Список занятий (бот)')
def list_lessons_telebot(message):
    if message.from_user.username != config.TUTOR_ID:
        send_notification(message.chat.id, "У вас нет доступа к этой функции.")
        return
    
    with session_scope() as session:
        lessons = session.query(Lesson).order_by(Lesson.date_time.desc()).limit(20).all()
        
        if not lessons:
            send_notification(message.chat.id, "Список занятий пуст.")
            return
        
        text = "📅 Последние занятия:\n\n"
        for lesson in lessons:
            status_emoji = {
                'запланирован': '🕐',
                'проведен': '✅',
                'отменен': '❌',
                'не_пришел': '🚫'
            }.get(lesson.status, '❓')
            
            date_str = lesson.date_time.strftime('%d.%m.%Y %H:%M')
            text += f"{status_emoji} {date_str}\n"
            text += f"   👤 {lesson.student.full_name}\n"
            text += f"   📊 {lesson.status}\n"
            if lesson.topic_covered:
                text += f"   📖 {lesson.topic_covered}\n"
            text += "\n"
        
        send_notification(message.chat.id, text)

@bot.message_handler(func=lambda message: message.text == '➕ Добавить занятие (бот)')
def add_lesson_telebot(message):
    if message.from_user.username != config.TUTOR_ID:
        send_notification(message.chat.id, "У вас нет доступа к этой функции.")
        return
    
    with session_scope() as session:
        students = session.query(Student).filter_by(is_archived=False).order_by(Student.full_name).all()
        
        if not students:
            send_notification(message.chat.id, "Нет активных студентов для добавления занятия.")
            return
        
        text = "Выберите студента для добавления занятия:\n\n"
        for student in students:
            text += f"ID {student.id}: {student.full_name}\n"
        
        text += "\nВведите данные в формате:\nID студента | дата время (ДД.ММ.ГГГГ ЧЧ:ММ)"
        
        send_notification(message.chat.id, text)
        bot.register_next_step_handler(message, process_add_lesson)

def process_add_lesson(message):
    try:
        parts = message.text.split('|')
        if len(parts) != 2:
            send_notification(message.chat.id, "Неверный формат. Используйте: ID студента | дата время")
            return
        
        student_id = int(parts[0].strip())
        datetime_str = parts[1].strip()
        
        # Парсим дату и время
        lesson_datetime = datetime.strptime(datetime_str, '%d.%m.%Y %H:%M')
        
        with session_scope() as session:
            student = session.get(Student, student_id)
            if not student:
                send_notification(message.chat.id, "Студент не найден")
                return
            
            lesson = Lesson(
                student_id=student_id,
                date_time=lesson_datetime,
                status='запланирован'
            )
            session.add(lesson)
            session.commit()
            
            # Уведомляем студента
            if student.telegram_chat_id and student.receive_notifications:
                lesson_time = lesson_datetime.strftime('%d.%m.%Y в %H:%M')
                send_notification(
                    student.telegram_chat_id,
                    f"📚 Запланировано новое занятие!\n\n"
                    f"Дата и время: {lesson_time}\n"
                    f"Не забудьте подготовиться!"
                )
            
            send_notification(message.chat.id, f"✅ Занятие с {student.full_name} добавлено на {datetime_str}")
    
    except ValueError:
        send_notification(message.chat.id, "Ошибка формата даты. Используйте: ДД.ММ.ГГГГ ЧЧ:ММ")
    except Exception as e:
        send_notification(message.chat.id, f"Ошибка добавления занятия: {e}")

@bot.message_handler(func=lambda message: message.text == '📅 Расписание на сегодня')
def today_schedule_telebot(message):
    chat_id = str(message.chat.id)
    
    # Проверяем, репетитор ли это
    if message.from_user.username == config.TUTOR_ID:
        with session_scope() as session:
            today = datetime.now().date()
            lessons = session.query(Lesson).filter(
                func.date(Lesson.date_time) == today
            ).order_by(Lesson.date_time).all()
            
            if not lessons:
                send_notification(message.chat.id, "📅 На сегодня занятий нет.")
                return
            
            text = f"📅 Расписание на {today.strftime('%d.%m.%Y')}:\n\n"
            for lesson in lessons:
                status_emoji = {
                    'запланирован': '🕐',
                    'проведен': '✅',
                    'отменен': '❌',
                    'не_пришел': '🚫'
                }.get(lesson.status, '❓')
                
                time_str = lesson.date_time.strftime('%H:%M')
                text += f"{status_emoji} {time_str} - {lesson.student.full_name}\n"
                text += f"   📊 Статус: {lesson.status}\n"
                if lesson.topic_covered:
                    text += f"   📖 Тема: {lesson.topic_covered}\n"
                text += "\n"
            
            send_notification(message.chat.id, text)
    else:
        # Для студентов показываем их расписание
        with session_scope() as session:
            student = session.query(Student).filter_by(telegram_chat_id=chat_id).first()
            if not student:
                send_notification(message.chat.id, "Вы не зарегистрированы в системе.")
                return
            
            today = datetime.now().date()
            lessons = session.query(Lesson).filter(
                Lesson.student_id == student.id,
                func.date(Lesson.date_time) == today
            ).order_by(Lesson.date_time).all()
            
            if not lessons:
                send_notification(message.chat.id, "📅 На сегодня у вас нет занятий.")
                return
            
            text = f"📅 Ваше расписание на {today.strftime('%d.%m.%Y')}:\n\n"
            for lesson in lessons:
                status_emoji = {
                    'запланирован': '🕐',
                    'проведен': '✅',
                    'отменен': '❌',
                    'не_пришел': '🚫'
                }.get(lesson.status, '❓')
                
                time_str = lesson.date_time.strftime('%H:%M')
                text += f"{status_emoji} {time_str}\n"
                text += f"   📊 Статус: {lesson.status}\n"
                if lesson.topic_covered:
                    text += f"   📖 Тема: {lesson.topic_covered}\n"
                if lesson.video_link:
                    text += f"   🎥 Видео: {lesson.video_link}\n"
                text += "\n"
            
            send_notification(message.chat.id, text)

@bot.message_handler(commands=['cancel_lesson'])
def cancel_lesson(message):
    if message.from_user.username != config.TUTOR_ID:
        send_notification(message.chat.id, "У вас нет доступа к этой команде.")
        return
    
    # Получаем ID урока из команды
    try:
        lesson_id = int(message.text.split()[1])
        
        with session_scope() as session:
            lesson = session.get(Lesson, lesson_id)
            if not lesson:
                send_notification(message.chat.id, "Урок не найден.")
                return
            
            lesson.status = 'отменен'
            session.commit()
            
            # Уведомляем студента
            student = lesson.student
            if student.telegram_chat_id and student.receive_notifications:
                lesson_time = lesson.date_time.strftime('%d.%m.%Y в %H:%M')
                send_notification(
                    student.telegram_chat_id,
                    f"❌ Занятие {lesson_time} отменено.\n"
                    f"Свяжитесь с репетитором для уточнения деталей."
                )
            
            send_notification(message.chat.id, f"✅ Урок с {student.full_name} отменен.")
    
    except (IndexError, ValueError):
        send_notification(message.chat.id, "Используйте: /cancel_lesson [ID урока]")
    except Exception as e:
        send_notification(message.chat.id, f"Ошибка отмены урока: {e}")

@bot.message_handler(commands=['complete_homework'])
def complete_homework_command(message):
    if message.from_user.username != config.TUTOR_ID:
        send_notification(message.chat.id, "У вас нет доступа к этой команде.")
        return
    
    # Получаем ID домашнего задания из команды
    try:
        homework_id = int(message.text.split()[1])
        
        with session_scope() as session:
            homework = session.get(Homework, homework_id)
            if not homework:
                send_notification(message.chat.id, "Домашнее задание не найдено.")
                return
            
            if not homework.submitted_date:
                send_notification(message.chat.id, "Это задание еще не отправлено студентом.")
                return
            
            homework.is_confirmed_by_tutor = True
            session.commit()
            
            # Уведомляем студента
            student = homework.student
            if student.telegram_chat_id and student.receive_notifications:
                send_notification(
                    student.telegram_chat_id,
                    f"✅ Ваше домашнее задание проверено и принято!\n\n"
                    f"Задание: {homework.description}"
                )
            
            send_notification(message.chat.id, f"✅ Домашнее задание студента {student.full_name} подтверждено.")
    
    except (IndexError, ValueError):
        send_notification(message.chat.id, "Используйте: /complete_homework [ID задания]")
    except Exception as e:
        send_notification(message.chat.id, f"Ошибка подтверждения задания: {e}")

# Обработчик для неизвестных команд от студентов
@bot.message_handler(func=lambda message: True)
def handle_unknown_message(message):
    chat_id = str(message.chat.id)
    
    # Проверяем, студент ли это
    with session_scope() as session:
        student = session.query(Student).filter_by(telegram_chat_id=chat_id).first()
        if student:
            # Предлагаем студенту использовать меню
            send_student_menu(message.chat.id, student)
        elif message.from_user.username == config.TUTOR_ID:
            # Для репетитора показываем меню
            send_tutor_menu(message.chat.id)
        else:
            send_notification(message.chat.id, 
                "Я не понимаю эту команду. Используйте /start для начала работы.")

# Импорт функций из sqlalchemy для работы с датами
from sqlalchemy import func

# Функция для запуска бота
def run_bot():
    print("Telegram бот запущен...")
    bot.infinity_polling()

if __name__ == '__main__':
    run_bot()