import sqlite3
from pathlib import Path

db_path = Path("db/sdr.sqlite3")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("--- Leads and their status ---")
cursor.execute("SELECT id, email, name, status, email_opt_out, touch_count FROM leads")
leads = cursor.fetchall()
for l in leads:
    print(l)

print("\n--- Campaign Leads ---")
cursor.execute("SELECT campaign_id, lead_id, emails_sent FROM campaign_leads")
cl = cursor.fetchall()
for r in cl:
    print(r)

conn.close()
