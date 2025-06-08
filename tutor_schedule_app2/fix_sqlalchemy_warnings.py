#!/usr/bin/env python3
"""
Скрипт для исправления предупреждений SQLAlchemy о устаревших методах.
Заменяет session.query(Model).get(id) на session.get(Model, id)
"""

import re
import os

def fix_sqlalchemy_warnings(file_path):
    """Исправляет предупреждения SQLAlchemy в указанном файле"""
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Паттерн для поиска session.query(Model).get(id)
    pattern = r'session\.query\((\w+)\)\.get\(([^)]+)\)'
    
    # Замена на session.get(Model, id)
    def replacement(match):
        model = match.group(1)
        id_param = match.group(2)
        return f'session.get({model}, {id_param})'
    
    # Выполняем замену
    new_content = re.sub(pattern, replacement, content)
    
    # Подсчитываем количество замен
    replacements_count = len(re.findall(pattern, content))
    
    if replacements_count > 0:
        # Записываем обновленный файл
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        print(f"✅ Исправлено {replacements_count} предупреждений в {file_path}")
    else:
        print(f"ℹ️  Предупреждений не найдено в {file_path}")
    
    return replacements_count

def main():
    """Основная функция"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    main_py_path = os.path.join(script_dir, 'main.py')
    
    print("🔧 Исправление предупреждений SQLAlchemy...")
    print(f"📁 Обрабатываем файл: {main_py_path}")
    
    if not os.path.exists(main_py_path):
        print(f"❌ Файл {main_py_path} не найден!")
        return
    
    total_fixes = fix_sqlalchemy_warnings(main_py_path)
    
    print(f"\n✨ Готово! Всего исправлено: {total_fixes} предупреждений")
    print("\n📋 Что было изменено:")
    print("   session.query(Model).get(id) → session.get(Model, id)")
    print("\n🚀 Теперь можно запускать приложение без предупреждений!")

if __name__ == "__main__":
    main()