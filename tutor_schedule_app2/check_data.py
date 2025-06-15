#!/usr/bin/env python3
"""
Скрипт для проверки данных в базе
"""

from database import Session, Student, User, Course, CourseEnrollment

def check_data():
    with Session() as session:
        # Проверяем пользователей
        users = session.query(User).all()
        print(f"👥 Всего пользователей: {len(users)}")
        for user in users:
            print(f"  - {user.username} ({user.role}) - ID: {user.id}")
        
        print()
        
        # Проверяем студентов
        students = session.query(Student).all()
        print(f"🎓 Всего студентов: {len(students)}")
        for student in students:
            print(f"  - {student.full_name} (Репетитор ID: {student.tutor_id}) - ID: {student.id}")
        
        print()
        
        # Проверяем курсы
        courses = session.query(Course).all()
        print(f"📚 Всего курсов: {len(courses)}")
        for course in courses:
            print(f"  - {course.title} (Репетитор ID: {course.tutor_id}) - ID: {course.id}")
        
        print()
        
        # Проверяем записи на курсы
        enrollments = session.query(CourseEnrollment).all()
        print(f"📋 Всего записей на курсы: {len(enrollments)}")
        for enrollment in enrollments:
            print(f"  - Курс {enrollment.course_id} -> Студент {enrollment.student_id}")

if __name__ == "__main__":
    check_data()