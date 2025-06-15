"""
Скрипт миграции для добавления системы курсов
"""

import sqlite3
import os
from contextlib import contextmanager
import config

@contextmanager
def db_connection():
    """Контекстный менеджер для подключения к БД"""
    conn = sqlite3.connect(config.DB_NAME)
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def check_courses_tables():
    """Проверяет существование таблиц для курсов"""
    tables_to_check = [
        'courses',
        'course_modules', 
        'course_lessons',
        'course_materials',
        'course_assignments',
        'course_enrollments',
        'course_submissions'
    ]
    
    with db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = [row[0] for row in cursor.fetchall()]
        
        missing_tables = [table for table in tables_to_check if table not in existing_tables]
        return len(missing_tables) == 0, missing_tables

def create_courses_tables():
    """Создает таблицы для системы курсов"""
    print("🔄 Создание таблиц для системы курсов...")
    
    sql_statements = [
        # Таблица курсов
        """
        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            tutor_id INTEGER NOT NULL,
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (tutor_id) REFERENCES users (id)
        );
        """,
        
        # Таблица модулей курса
        """
        CREATE TABLE IF NOT EXISTS course_modules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            order_index INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (course_id) REFERENCES courses (id) ON DELETE CASCADE
        );
        """,
        
        # Таблица уроков
        """
        CREATE TABLE IF NOT EXISTS course_lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT,
            order_index INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (module_id) REFERENCES course_modules (id) ON DELETE CASCADE
        );
        """,
        
        # Таблица материалов урока
        """
        CREATE TABLE IF NOT EXISTS course_materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lesson_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            material_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER,
            original_filename TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (lesson_id) REFERENCES course_lessons (id) ON DELETE CASCADE
        );
        """,
        
        # Таблица заданий
        """
        CREATE TABLE IF NOT EXISTS course_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lesson_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            assignment_type TEXT DEFAULT 'text',
            is_required BOOLEAN DEFAULT 1,
            max_points INTEGER DEFAULT 100,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (lesson_id) REFERENCES course_lessons (id) ON DELETE CASCADE
        );
        """,
        
        # Таблица зачислений студентов на курсы
        """
        CREATE TABLE IF NOT EXISTS course_enrollments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            enrolled_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1,
            progress_percentage REAL DEFAULT 0.0,
            FOREIGN KEY (course_id) REFERENCES courses (id) ON DELETE CASCADE,
            FOREIGN KEY (student_id) REFERENCES students (id) ON DELETE CASCADE,
            UNIQUE(course_id, student_id)
        );
        """,
        
        # Taблица выполненных заданий
        """
        CREATE TABLE IF NOT EXISTS course_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL,
            enrollment_id INTEGER NOT NULL,
            content TEXT,
            file_path TEXT,
            submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_checked BOOLEAN DEFAULT 0,
            points INTEGER,
            tutor_feedback TEXT,
            checked_at DATETIME,
            FOREIGN KEY (assignment_id) REFERENCES course_assignments (id) ON DELETE CASCADE,
            FOREIGN KEY (enrollment_id) REFERENCES course_enrollments (id) ON DELETE CASCADE
        );
        """
    ]
    
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            
            for sql in sql_statements:
                cursor.execute(sql)
            
            print("✅ Таблицы курсов созданы успешно!")
            return True
            
    except Exception as e:
        print(f"❌ Ошибка создания таблиц: {e}")
        return False

def migrate_courses():
    """Основная функция миграции"""
    print("=== Миграция системы курсов ===")
    
    # Проверяем существование БД
    if not os.path.exists(config.DB_NAME):
        print(f"❌ База данных {config.DB_NAME} не найдена!")
        print("Запустите сначала create_admin.py или migrate_db.py")
        return False
    
    # Проверяем наличие таблиц курсов
    tables_exist, missing_tables = check_courses_tables()
    
    if tables_exist:
        print("✅ Таблицы курсов уже существуют")
        return True
    
    print(f"⚠️ Отсутствуют таблицы: {', '.join(missing_tables)}")
    
    # Создаем таблицы
    if create_courses_tables():
        print("🎉 Миграция курсов завершена успешно!")
        print("\nТеперь вы можете:")
        print("- Создавать курсы через веб-интерфейс")
        print("- Добавлять модули и уроки")
        print("- Загружать материалы")
        print("- Назначать курсы студентам")
        return True
    else:
        print("❌ Миграция не удалась")
        return False

if __name__ == '__main__':
    migrate_courses()