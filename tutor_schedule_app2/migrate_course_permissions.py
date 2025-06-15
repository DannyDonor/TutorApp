#!/usr/bin/env python3
"""
Миграция для добавления поля can_create_courses в таблицу users
"""

import sqlite3
import os
import config

def add_course_permission_field():
    """Добавляет поле can_create_courses в таблицу users"""
    db_path = config.DB_NAME
    
    if not os.path.exists(db_path):
        print(f"❌ База данных {db_path} не найдена")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Проверяем, существует ли уже поле can_create_courses
        cursor.execute("PRAGMA table_info(users)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'can_create_courses' not in columns:
            # Добавляем поле can_create_courses
            cursor.execute("""
                ALTER TABLE users 
                ADD COLUMN can_create_courses BOOLEAN DEFAULT 0
            """)
            print("✅ Добавлено поле can_create_courses")
            
            # Даем права администраторам на создание курсов
            cursor.execute("""
                UPDATE users 
                SET can_create_courses = 1 
                WHERE role = 'admin'
            """)
            print("✅ Администраторам предоставлены права на создание курсов")
            
            # Показываем статистику
            cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'tutor' AND is_approved = 1")
            approved_tutors = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'tutor' AND can_create_courses = 1")
            tutors_with_permission = cursor.fetchone()[0]
            
            print(f"📊 Одобренных репетиторов: {approved_tutors}")
            print(f"📊 Репетиторов с правами создания курсов: {tutors_with_permission}")
            print("ℹ️  Администратор может предоставить права на создание курсов в разделе 'Пользователи'")
            
        else:
            print("✅ Поле can_create_courses уже существует")
        
        conn.commit()
        conn.close()
        
        print("✅ Миграция разрешений на курсы завершена успешно")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при миграции разрешений на курсы: {e}")
        return False

def main():
    """Основная функция миграции"""
    print("🔄 Запуск миграции для разрешений на создание курсов...")
    
    if add_course_permission_field():
        print("✅ Миграция завершена успешно!")
        return True
    else:
        print("❌ Миграция завершилась с ошибками")
        return False

if __name__ == "__main__":
    main()