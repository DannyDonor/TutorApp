#!/usr/bin/env python3
"""
Миграция для добавления поля status в course_submissions
"""

import sqlite3
import os
import config

def add_status_field():
    """Добавляет поле status в таблицу course_submissions"""
    db_path = config.DB_NAME
    
    if not os.path.exists(db_path):
        print(f"❌ База данных {db_path} не найдена")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Проверяем, существует ли уже поле status
        cursor.execute("PRAGMA table_info(course_submissions)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'status' not in columns:
            # Добавляем поле status
            cursor.execute("""
                ALTER TABLE course_submissions 
                ADD COLUMN status TEXT DEFAULT 'submitted'
            """)
            print("✅ Добавлено поле status")
            
            # Обновляем статус для проверенных заданий
            cursor.execute("""
                UPDATE course_submissions 
                SET status = 'approved' 
                WHERE is_checked = 1
            """)
            print("✅ Обновлены статусы проверенных заданий")
        else:
            print("✅ Поле status уже существует")
        
        conn.commit()
        conn.close()
        
        print("✅ Миграция статусов заданий завершена успешно")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при миграции статусов заданий: {e}")
        return False

def main():
    """Основная функция миграции"""
    print("🔄 Запуск миграции для статусов заданий...")
    
    if add_status_field():
        print("✅ Миграция завершена успешно!")
        return True
    else:
        print("❌ Миграция завершилась с ошибками")
        return False

if __name__ == "__main__":
    main()