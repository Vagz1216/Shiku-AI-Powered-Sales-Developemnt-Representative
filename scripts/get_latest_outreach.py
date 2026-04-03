import sqlite3
from pathlib import Path

db_path = Path("db/sdr.sqlite3")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("--- Latest Outbound Email ---")
cursor.execute("""
    SELECT em.subject, em.body, l.email, l.name, em.created_at 
    FROM email_messages em
    JOIN leads l ON em.lead_id = l.id
    WHERE em.direction = 'outbound'
    ORDER BY em.created_at DESC
    LIMIT 1
""")
result = cursor.fetchone()
if result:
    subject, body, email, name, created_at = result
    print(f"Recipient: {name} ({email})")
    print(f"Sent at: {created_at}")
    print(f"Subject: {subject}")
    print(f"\nBody:\n{body}")
else:
    print("No outbound emails found in the database.")

conn.close()
