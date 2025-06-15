"""
Система миграции базы данных TutorApp
"""

import sqlite3
import os
import shutil
import config
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

def backup_database():
    """Создает резервную копию базы данных"""
    if os.path.exists(config.DB_NAME):
        backup_name = f"{config.DB_NAME}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(config.DB_NAME, backup_name)
        print(f"✅ Резервная копия создана: {backup_name}")
        return backup_name
    return None

def check_database_structure():
    """Проверяет актуальность структуры базы данных"""
    try:
        conn = sqlite3.connect(config.DB_NAME)
        cursor = conn.cursor()
        
        # Проверяем, есть ли поле tutor_id в таблице students
        cursor.execute("PRAGMA table_info(students)")
        columns = [row[1] for row in cursor.fetchall()]
        
        needs_migration = False
        missing_columns = []
        
        if 'tutor_id' not in columns:
            missing_columns.append('tutor_id')
            needs_migration = True
        
        conn.close()
        
        return needs_migration, missing_columns
    
    except Exception as e:
        print(f"❌ Ошибка проверки структуры БД: {e}")
        return True, ['unknown_error']

def apply_migrations():
    """Применяет миграции к базе данных"""
    try:
        conn = sqlite3.connect(config.DB_NAME)
        cursor = conn.cursor()
        
        print("📝 Применение миграций...")
        
        # Миграция 1: Добавление поля tutor_id в таблицу students
        try:
            cursor.execute("ALTER TABLE students ADD COLUMN tutor_id INTEGER")
            print("✅ Добавлено поле tutor_id в таблицу students")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print("ℹ️ Поле tutor_id уже существует")
            else:
                raise e
        
        # Миграция 2: Создание индекса для tutor_id
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_students_tutor_id ON students(tutor_id)")
            print("✅ Создан индекс для tutor_id")
        except sqlite3.OperationalError as e:
            print(f"⚠️ Не удалось создать индекс: {e}")
        
        conn.commit()
        conn.close()
        
        print("✅ Все миграции применены успешно!")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка применения миграций: {e}")
        return False

def recreate_database():
    """Пересоздает базу данных с нуля"""
    try:
        # Создаем резервную копию
        backup_file = backup_database()
        
        # Удаляем старую БД
        if os.path.exists(config.DB_NAME):
            os.remove(config.DB_NAME)
            print("🗑️ Старая база данных удалена")
        
        # Создаем новую БД
        from database import engine, Base
        Base.metadata.create_all(engine)
        print("✅ Новая база данных создана")
        
        # Предлагаем восстановить данные из резервной копии
        if backup_file and os.path.exists(backup_file):
            print(f"\n📋 Резервная копия доступна: {backup_file}")
            print("   Вы можете вручную восстановить данные из резервной копии.")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка пересоздания БД: {e}")
        return False

def interactive_migration():
    """Интерактивная миграция с диалоговыми окнами"""
    print("=" * 60)
    print("🔧 СИСТЕМА МИГРАЦИИ БАЗЫ ДАННЫХ TutorApp")
    print("=" * 60)
    
    # Проверяем актуальность БД
    needs_migration, missing_columns = check_database_structure()
    
    if not needs_migration:
        print("✅ База данных актуальна, миграция не требуется")
        return True
    
    print("⚠️ База данных требует обновления!")
    print(f"   Отсутствующие поля: {', '.join(missing_columns)}")
    print()
    
    print("Доступные варианты:")
    print("1. 🔄 Применить миграции (попытаться обновить существующую БД)")
    print("2. 🆕 Пересоздать БД с нуля (все данные будут потеряны, но создастся резервная копия)")
    print("3. ❌ Отмена (оставить как есть)")
    print()
    
    while True:
        choice = input("Выберите вариант (1/2/3): ").strip()
        
        if choice == '1':
            print("\n🔄 Применение миграций...")
            
            # Создаем резервную копию перед миграцией
            backup_file = backup_database()
            
            if apply_migrations():
                print("\n✅ Миграция завершена успешно!")
                print("   Теперь можно запускать приложение.")
                return True
            else:
                print("\n❌ Миграция не удалась!")
                if backup_file:
                    print(f"   Резервная копия: {backup_file}")
                return False
                
        elif choice == '2':
            print("\n⚠️ ВНИМАНИЕ: Все данные будут потеряны!")
            confirm = input("Вы уверены? Введите 'ДА' для подтверждения: ").strip()
            
            if confirm.upper() == 'ДА':
                print("\n🆕 Пересоздание базы данных...")
                if recreate_database():
                    print("\n✅ База данных пересоздана!")
                    print("   Теперь можно запускать приложение.")
                    return True
                else:
                    return False
            else:
                print("   Операция отменена.")
                continue
                
        elif choice == '3':
            print("\n❌ Миграция отменена.")
            print("   Приложение может работать нестабильно!")
            return False
            
        else:
            print("❌ Неверный выбор. Попробуйте снова.")

def quick_fix():
    """Быстрое исправление без диалогов (для автоматического запуска)"""
    needs_migration, missing_columns = check_database_structure()
    
    if not needs_migration:
        return True
    
    print("⚠️ База данных требует обновления. Применяю быстрые исправления...")
    
    backup_file = backup_database()
    
    if apply_migrations():
        print("✅ Быстрое исправление применено успешно!")
        return True
    else:
        print("❌ Быстрое исправление не удалось. Требуется ручная миграция.")
        return False

if __name__ == '__main__':
    interactive_migration()