from typing import Optional

from utils.db_connection import get_conn, dict_from_row


def get_staff(staff_id: Optional[int] = None, exclude_email: Optional[str] = None) -> Optional[dict]:
    """Return staff details by id, or a random staff if id is None.
    
    Args:
        staff_id: Specific staff member ID. If None, returns a random staff member.
        exclude_email: Email to exclude from random selection (prevents notifying the client as staff).
    """
    conn = get_conn()
    if staff_id:
        cur = conn.execute("SELECT name, email, timezone, availability FROM staff WHERE id = ?", (staff_id,))
    elif exclude_email:
        cur = conn.execute(
            "SELECT name, email, timezone, availability FROM staff WHERE LOWER(email) != LOWER(?) ORDER BY RANDOM() LIMIT 1",
            (exclude_email,),
        )
    else:
        cur = conn.execute("SELECT name, email, timezone, availability FROM staff ORDER BY RANDOM() LIMIT 1")
    row = cur.fetchone()
    return dict_from_row(row)
