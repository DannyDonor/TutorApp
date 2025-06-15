#!/usr/bin/env python3
"""
Миграция для добавления полей отслеживания прогресса в course_enrollments
"""

import sqlite3
import os
import config

def add_progress_fields():
    """Добавляет поля для отслеживания прогресса в таблицу course_enrollments"""
    db_path = config.DB_NAME
    
    if not os.path.exists(db_path):
        print(f"❌ База данных {db_path} не найдена")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Проверяем, существуют ли уже новые поля
        cursor.execute("PRAGMA table_info(course_enrollments)")
        columns = [col[1] for col in cursor.fetchall()]
        
        # Добавляем поле current_lesson_id если его нет
        if 'current_lesson_id' not in columns:
            cursor.execute("""
                ALTER TABLE course_enrollments 
                ADD COLUMN current_lesson_id INTEGER
            """)
            print("✅ Добавлено поле current_lesson_id")
        else:
            print("✅ Поле current_lesson_id уже существует")
        
        # Добавляем поле completed_lessons если его нет
        if 'completed_lessons' not in columns:
            cursor.execute("""
                ALTER TABLE course_enrollments 
                ADD COLUMN completed_lessons TEXT DEFAULT ''
            """)
            print("✅ Добавлено поле completed_lessons")
        else:
            print("✅ Поле completed_lessons уже существует")
        
        # Инициализируем current_lesson_id для существующих записей
        cursor.execute("""
            UPDATE course_enrollments 
            SET current_lesson_id = (
                SELECT cl.id 
                FROM course_lessons cl 
                JOIN course_modules cm ON cl.module_id = cm.id 
                WHERE cm.course_id = course_enrollments.course_id 
                ORDER BY cm.order_index, cl.order_index 
                LIMIT 1
            )
            WHERE current_lesson_id IS NULL
        """)
        
        # Инициализируем completed_lessons пустой строкой
        cursor.execute("""
            UPDATE course_enrollments 
            SET completed_lessons = '' 
            WHERE completed_lessons IS NULL
        """)
        
        conn.commit()
        conn.close()
        
        print("✅ Миграция прогресса курсов завершена успешно")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при миграции прогресса курсов: {e}")
        return False

def main():
    """Основная функция миграции"""
    print("🔄 Запуск миграции для отслеживания прогресса курсов...")
    
    if add_progress_fields():
        print("✅ Миграция завершена успешно!")
        return True
    else:
        print("❌ Миграция завершилась с ошибками")
        return False

if __name__ == "__main__":
    main()