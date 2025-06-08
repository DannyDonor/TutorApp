#!/usr/bin/env python3
"""
Скрипт для миграции статусов уроков на русский язык
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import engine, Base, Lesson
from sqlalchemy.orm import sessionmaker

# Создаем сессию
Session = sessionmaker(bind=engine)

def migrate_lesson_statuses():
    """Миграция статусов уроков на русский язык"""
    
    session = Session()
    
    try:
        print("🔄 Начинаем миграцию статусов уроков...")
        
        # Словарь для перевода статусов
        status_mapping = {
            'scheduled': 'запланирован',
            'completed': 'проведен', 
            'cancelled': 'отменен',
            'no_show': 'не_пришел'
        }
        
        # Получаем все уроки
        lessons = session.query(Lesson).all()
        
        updated_count = 0
        
        for lesson in lessons:
            old_status = lesson.status
            if old_status in status_mapping:
                lesson.status = status_mapping[old_status]
                updated_count += 1
                print(f"  📝 Урок {lesson.id}: {old_status} → {lesson.status}")
        
        # Также обновляем report_status если нужно
        for lesson in lessons:
            old_report_status = lesson.report_status
            if old_report_status in status_mapping:
                lesson.report_status = status_mapping[old_report_status]
                print(f"  📋 Отчет урока {lesson.id}: {old_report_status} → {lesson.report_status}")
        
        # Сохраняем изменения
        session.commit()
        
        print(f"\n✅ Миграция завершена!")
        print(f"📊 Обновлено уроков: {updated_count}")
        print(f"📊 Всего уроков в БД: {len(lessons)}")
        
        # Показываем статистику по статусам
        print(f"\n📈 Статистика по статусам:")
        for status in ['запланирован', 'проведен', 'отменен', 'не_пришел']:
            count = session.query(Lesson).filter(Lesson.status == status).count()
            print(f"  {status}: {count}")
            
    except Exception as e:
        print(f"❌ Ошибка при миграции: {e}")
        session.rollback()
        raise
    finally:
        session.close()

if __name__ == "__main__":
    migrate_lesson_statuses()