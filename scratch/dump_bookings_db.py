import sqlite3
try:
    conn = sqlite3.connect('bookings.db')
    cursor = conn.cursor()
    cursor.execute("SELECT name, description, features FROM services_service")
    rows = cursor.fetchall()
    for row in rows:
        print(f"Name: {row[0]}")
        print(f"Desc: {row[1]}")
        print(f"Feat: {row[2]}")
        print("-" * 20)
    conn.close()
except Exception as e:
    print(f"Error: {e}")
