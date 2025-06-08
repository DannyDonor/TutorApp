#!/usr/bin/env python3
"""
Миграция для добавления новых полей в таблицы homeworks и lessons
"""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import config

def migrate_database():
    engine = create_engine(f'sqlite:///{config.DB_NAME}')
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        # Добавляем новые поля в таблицу homeworks
        try:
            session.execute(text("ALTER TABLE homeworks ADD COLUMN student_comment TEXT"))
            print("Добавлено поле student_comment в таблицу homeworks")
        except Exception as e:
            print(f"Поле student_comment уже существует или ошибка: {e}")
        
        try:
            session.execute(text("ALTER TABLE homeworks ADD COLUMN is_confirmed_by_tutor BOOLEAN DEFAULT 0"))
            print("Добавлено поле is_confirmed_by_tutor в таблицу homeworks")
        except Exception as e:
            print(f"Поле is_confirmed_by_tutor уже существует или ошибка: {e}")
        
        try:
            session.execute(text("ALTER TABLE homeworks ADD COLUMN submitted_date DATETIME"))
            print("Добавлено поле submitted_date в таблицу homeworks")
        except Exception as e:
            print(f"Поле submitted_date уже существует или ошибка: {e}")
        
        # Добавляем новое поле в таблицу lessons
        try:
            session.execute(text("ALTER TABLE lessons ADD COLUMN video_status TEXT DEFAULT 'pending'"))
            print("Добавлено поле video_status в таблицу lessons")
        except Exception as e:
            print(f"Поле video_status уже существует или ошибка: {e}")
        
        session.commit()
        print("Миграция завершена успешно!")
        
    except Exception as e:
        session.rollback()
        print(f"Ошибка миграции: {e}")
    finally:
        session.close()

if __name__ == '__main__':
    migrate_database()