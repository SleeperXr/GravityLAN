import asyncio
import logging
from collections import deque
from typing import Set
from fastapi import WebSocket

class LogStreamerHandler(logging.Handler):
    """
    Custom logging handler that buffers log records and 
    allows them to be streamed via WebSockets.
    """
    def __init__(self, capacity: int = 200):
        super().__init__()
        self.buffer = deque(maxlen=capacity)
        self.subscribers: Set[WebSocket] = set()
        self.loop = asyncio.get_event_loop()

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            self.buffer.append(msg)
            
            # Broadcast to active WebSocket subscribers
            # We use call_soon_threadsafe because emit might be called from a thread
            if self.subscribers:
                self.loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(self._broadcast(msg))
                )
        except Exception:
            self.handleError(record)

    async def _broadcast(self, msg: str):
        if not self.subscribers:
            return
        
        dead_links = set()
        for ws in list(self.subscribers):
            try:
                await ws.send_text(msg)
            except Exception:
                dead_links.add(ws)
        
        for ws in dead_links:
            self.subscribers.remove(ws)

    def subscribe(self, websocket: WebSocket):
        self.subscribers.add(websocket)

    def unsubscribe(self, websocket: WebSocket):
        if websocket in self.subscribers:
            self.subscribers.remove(websocket)

    def get_history(self):
        return list(self.buffer)

# Global instance
log_handler = LogStreamerHandler()
log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

def apply_log_level(lvl_str: str):
    """
    Apply a log level string to the application loggers.
    Supports DEBUG, INFO, WARNING, ERROR, and the custom DEBUG_SQL.
    """
    lvl_str = lvl_str.upper()
    root_logger = logging.getLogger()
    sql_logger = logging.getLogger("sqlalchemy.engine")
    sqlite_logger = logging.getLogger("aiosqlite")

    # Explicit mapping to avoid getattr pitfalls
    LEVEL_MAP = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "WARN": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL
    }

    if lvl_str == "DEBUG_SQL":
        sql_logger.setLevel(logging.INFO)
        sqlite_logger.setLevel(logging.INFO)
        root_logger.setLevel(logging.DEBUG)
        logging.getLogger("app").setLevel(logging.DEBUG)
    else:
        lvl = LEVEL_MAP.get(lvl_str, logging.INFO)
        root_logger.setLevel(lvl)
        logging.getLogger("app").setLevel(lvl)
        
        # Keep SQL logs suppressed unless in DEBUG_SQL mode
        logging.getLogger("sqlalchemy").setLevel(max(lvl, logging.WARNING))
        sql_logger.setLevel(max(lvl, logging.WARNING))
        sqlite_logger.setLevel(max(lvl, logging.WARNING))
        logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    
    # Ensure this message is visible even if switching TO a higher level
    root_logger.log(max(logging.INFO, root_logger.level), "Log level updated to: %s", lvl_str)
