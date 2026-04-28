from typing import Optional

from utils.db_connection import get_conn, dict_from_row, sql_random_order


def get_staff(
    staff_id: Optional[int] = None,
    exclude_email: Optional[str] = None,
    campaign_id: Optional[int] = None,
) -> Optional[dict]:
    """Return staff details by id, or a random staff if id is None.
    
    Args:
        staff_id: Specific staff member ID. If None, returns a random staff member.
        exclude_email: Email to exclude from random selection (prevents notifying the client as staff).
        campaign_id: If provided, constrain random selection to staff assigned to this campaign.
    """
    conn = get_conn()
    if staff_id:
        cur = conn.execute("SELECT name, email, timezone, availability FROM staff WHERE id = ?", (staff_id,))
    elif campaign_id and exclude_email:
        rnd = sql_random_order()
        cur = conn.execute(
            "SELECT s.name, s.email, s.timezone, s.availability "
            "FROM campaign_staff cs "
            "JOIN staff s ON s.id = cs.staff_id "
            "WHERE cs.campaign_id = ? AND LOWER(s.email) != LOWER(?) "
            f"ORDER BY {rnd} LIMIT 1",
            (campaign_id, exclude_email),
        )
    elif campaign_id:
        rnd = sql_random_order()
        cur = conn.execute(
            "SELECT s.name, s.email, s.timezone, s.availability "
            "FROM campaign_staff cs "
            "JOIN staff s ON s.id = cs.staff_id "
            "WHERE cs.campaign_id = ? "
            f"ORDER BY {rnd} LIMIT 1",
            (campaign_id,),
        )
    elif exclude_email:
        rnd = sql_random_order()
        cur = conn.execute(
            f"SELECT name, email, timezone, availability FROM staff WHERE LOWER(email) != LOWER(?) ORDER BY {rnd} LIMIT 1",
            (exclude_email,),
        )
    else:
        rnd = sql_random_order()
        cur = conn.execute(f"SELECT name, email, timezone, availability FROM staff ORDER BY {rnd} LIMIT 1")
    row = cur.fetchone()
    return dict_from_row(row)
