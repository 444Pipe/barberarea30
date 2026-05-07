import sqlite3

try:
    conn = sqlite3.connect('bookings.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE barbers_barber SET commission_percentage = 50 WHERE display_name LIKE '%frank%';")
    cursor.execute("UPDATE barbers_barber SET commission_percentage = 40 WHERE display_name NOT LIKE '%frank%';")
    conn.commit()
    print("Database updated successfully.")
    
    cursor.execute("SELECT display_name, commission_percentage FROM barbers_barber;")
    for row in cursor.fetchall():
        print(f"{row[0]}: {row[1]}")
    conn.close()
except Exception as e:
    print(f"Error: {e}")
