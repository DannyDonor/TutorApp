"""
Тестовый скрипт для запуска только веб-части приложения
"""

def main():
    print("=== Запуск веб-части TutorApp ===")
    
    # Проверяем и применяем миграции
    try:
        from migrate_db import check_database_structure, interactive_migration
        
        needs_migration, missing_columns = check_database_structure()
        if needs_migration:
            print("\n⚠️ База данных требует обновления!")
            print("Запуск системы миграции...\n")
            
            if not interactive_migration():
                print("❌ Не удалось обновить базу данных. Завершение работы.")
                return
    except Exception as e:
        print(f"⚠️ Ошибка проверки миграции: {e}")
        print("Попытка продолжить работу...")
    
    # Импортируем после возможной миграции
    try:
        from main_web import app, create_default_admin
        
        # Создаем администратора по умолчанию
        create_default_admin()
        
        print("\n✅ Приложение готово к запуску!")
        print("Веб-интерфейс: http://localhost:5000")
        print("Администратор: admin / admin123")
        print("Для остановки нажмите Ctrl+C\n")
        
        app.run(debug=True, port=5000)
        
    except Exception as e:
        print(f"❌ Ошибка запуска приложения: {e}")
        print("Попробуйте запустить migrate_db.py для исправления проблем с БД")

if __name__ == '__main__':
    main()