import sqlite3
from pathlib import Path

db_path = Path("db/sdr.sqlite3")
if not db_path.exists():
    print(f"Database {db_path} does not exist.")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("--- Active Campaigns ---")
cursor.execute("SELECT id, name, status FROM campaigns WHERE status = 'ACTIVE'")
campaigns = cursor.fetchall()
for c in campaigns:
    print(c)

print("\n--- Eligible Leads (Status: NEW, No Opt-Out) ---")
cursor.execute("SELECT COUNT(*) FROM leads WHERE email_opt_out = 0 AND status = 'NEW'")
lead_count = cursor.fetchone()[0]
print(f"Count: {lead_count}")

conn.close()
