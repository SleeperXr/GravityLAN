"""
Database maintenance script to fix NULL values in the devices table.
Ensures essential fields like 'status_changed_at' and 'is_online' have sensible defaults.
"""

from datetime import datetime
from scripts.db_utils import setup_script_logging, run_maintenance_sql

def main():
    """Identifies and repairs NULL values in critical database columns."""
    setup_script_logging()
    now = datetime.now().isoformat()

    # 1. Update status_changed_at
    run_maintenance_sql(
        "Update status_changed_at defaults",
        "UPDATE devices SET status_changed_at = ? WHERE status_changed_at IS NULL",
        (now,)
    )

    # 2. Update is_online
    run_maintenance_sql(
        "Update is_online defaults",
        "UPDATE devices SET is_online = 1 WHERE is_online IS NULL"
    )

if __name__ == "__main__":
    main()
