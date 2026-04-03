import sqlite3
from pathlib import Path

db_path = Path("db/sdr.sqlite3")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Reset Martin Kamau for testing
cursor.execute("UPDATE leads SET status = 'NEW', touch_count = 0 WHERE email = 'myskill254@gmail.com'")
cursor.execute("UPDATE campaign_leads SET emails_sent = 0 WHERE lead_id = 7 AND campaign_id = 1")

# Also reset some others
cursor.execute("UPDATE leads SET status = 'NEW', touch_count = 0 WHERE email IN ('alice@example.com', 'bob@example.com')")
cursor.execute("UPDATE campaign_leads SET emails_sent = 0 WHERE lead_id IN (1, 2) AND campaign_id = 1")

conn.commit()
print("Database updated to allow new outreach test.")
conn.close()
