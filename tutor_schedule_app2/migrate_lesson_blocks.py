#!/usr/bin/env python3
"""
Миграция для добавления таблицы lesson_blocks
"""

import sqlite3
import os
import config

def create_lesson_blocks_table():
    """Создает таблицу lesson_blocks"""
    db_path = config.DB_NAME
    
    if not os.path.exists(db_path):
        print(f"❌ База данных {db_path} не найдена")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Проверяем, существует ли таблица
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='lesson_blocks'
        """)
        
        if cursor.fetchone():
            print("✅ Таблица lesson_blocks уже существует")
            conn.close()
            return True
        
        # Создаем таблицу lesson_blocks
        cursor.execute("""
            CREATE TABLE lesson_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lesson_id INTEGER NOT NULL,
                block_type VARCHAR(50) NOT NULL,
                title VARCHAR(255),
                content TEXT,
                material_id INTEGER,
                order_index INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (lesson_id) REFERENCES course_lessons (id) ON DELETE CASCADE,
                FOREIGN KEY (material_id) REFERENCES course_materials (id) ON DELETE SET NULL
            )
        """)
        
        # Создаем индексы для оптимизации
        cursor.execute("""
            CREATE INDEX idx_lesson_blocks_lesson_id ON lesson_blocks (lesson_id)
        """)
        
        cursor.execute("""
            CREATE INDEX idx_lesson_blocks_order ON lesson_blocks (lesson_id, order_index)
        """)
        
        conn.commit()
        conn.close()
        
        print("✅ Таблица lesson_blocks создана успешно")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при создании таблицы lesson_blocks: {e}")
        return False

def main():
    """Основная функция миграции"""
    print("🔄 Запуск миграции для lesson_blocks...")
    
    if create_lesson_blocks_table():
        print("✅ Миграция lesson_blocks завершена успешно!")
        return True
    else:
        print("❌ Миграция lesson_blocks завершилась с ошибками")
        return False

if __name__ == "__main__":
    main()