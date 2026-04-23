from typing import Optional

from utils.db_connection import get_conn, dict_from_row


def get_staff(staff_id: Optional[int] = None) -> Optional[dict]:
    """Return staff details by id, or a random staff if id is None."""
    conn = get_conn()
    if staff_id:
        cur = conn.execute("SELECT name, email, timezone, availability FROM staff WHERE id = ?", (staff_id,))
    else:
        cur = conn.execute("SELECT name, email, timezone, availability FROM staff ORDER BY RANDOM() LIMIT 1")
    row = cur.fetchone()
    return dict_from_row(row)
