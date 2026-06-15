"""System logs API endpoint for GravityLAN."""

import logging
import re
from fastapi import APIRouter, Depends, Query
from app.api.auth import get_current_admin
from app.services.log_streamer import log_handler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/logs", tags=["logs"])

LOG_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) \[([A-Z]+)\] \[([^\]]*)\] ([^:]+): (.*)$"
)

def parse_log_line(line: str) -> dict:
    match = LOG_PATTERN.match(line)
    if match:
        ts_str, level, cid, logger_name, message = match.groups()
        return {
            "timestamp": ts_str,
            "level": level,
            "correlation_id": cid if cid != "-" else None,
            "logger": logger_name,
            "message": message
        }
    return {
        "timestamp": None,
        "level": "INFO",
        "correlation_id": None,
        "logger": "raw",
        "message": line
    }

@router.get("", response_model=list[dict])
async def get_logs(
    limit: int = Query(50, ge=1, le=1000),
    level: str | None = Query(None, description="Filter logs by level (e.g. INFO, ERROR)"),
    current_admin: str = Depends(get_current_admin)
):
    """Fetch structured system logs from the in-memory log buffer."""
    history = log_handler.get_history()
    parsed_logs = []
    
    # Iterate from newest to oldest logs
    for line in reversed(history):
        parsed = parse_log_line(line)
        if level and parsed["level"].upper() != level.upper():
            continue
        parsed_logs.append(parsed)
        if len(parsed_logs) >= limit:
            break
            
    return parsed_logs
