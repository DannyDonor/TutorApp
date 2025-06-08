#!/usr/bin/env python3
"""
Скрипт для инициализации базы данных с новыми таблицами
"""

from database import Base, engine, Session, User
from datetime import datetime
from sqlalchemy import text

def migrate_database():
    """Выполняет миграцию базы данных"""
    session = Session()
    try:
        # Добавляем новые колонки если их нет
        try:
            # Добавляем bot_token в users
            session.execute(text("ALTER TABLE users ADD COLUMN bot_token VARCHAR"))
            print("Добавлена колонка bot_token в таблицу users")
        except Exception:
            print("Колонка bot_token уже существует в таблице users")
        
        try:
            # Переименовываем telegram_id в telegram_chat_id в students
            session.execute(text("ALTER TABLE students RENAME COLUMN telegram_id TO telegram_chat_id"))
            print("Переименована колонка telegram_id -> telegram_chat_id в таблице students")
        except Exception:
            print("Колонка telegram_chat_id уже существует в таблице students")
        
        try:
            # Переименовываем telegram_id в telegram_chat_id в parents
            session.execute(text("ALTER TABLE parents RENAME COLUMN telegram_id TO telegram_chat_id"))
            print("Переименована колонка telegram_id -> telegram_chat_id в таблице parents")
        except Exception:
            print("Колонка telegram_chat_id уже существует в таблице parents")
        
        session.commit()
        print("Миграция завершена успешно!")
        
    except Exception as e:
        print(f"Ошибка при миграции: {e}")
        session.rollback()
    finally:
        session.close()

def init_database():
    """Создает все таблицы в базе данных"""
    print("Создание таблиц...")
    Base.metadata.create_all(engine)
    print("Таблицы созданы успешно!")
    
    # Выполняем миграцию
    migrate_database()
    
    # Создаем администратора по умолчанию
    session = Session()
    try:
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
            print("Создан администратор по умолчанию:")
            print("Логин: admin")
            print("Пароль: admin123")
        else:
            print("Администратор уже существует")
    except Exception as e:
        print(f"Ошибка при создании администратора: {e}")
        session.rollback()
    finally:
        session.close()

if __name__ == '__main__':
    init_database()