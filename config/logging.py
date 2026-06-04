"""Logging configuration for the application."""

import json
import logging
import logging.handlers
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

# Global flag to prevent multiple logging setup
_logging_configured = False
_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_RESERVED_LOG_RECORD_ATTRS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
    "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
    "relativeCreated", "thread", "threadName", "processName", "process", "message",
    "asctime", "request_id", "component", "kind", "taskName",
}


def set_request_id(request_id: str):
    """Bind a request ID to the current async context."""
    return _request_id.set(request_id)


def reset_request_id(token) -> None:
    """Reset the request ID context after a request completes."""
    _request_id.reset(token)


def get_request_id() -> str:
    """Return the current request ID for structured logs."""
    return _request_id.get()


class JSONFormatter(logging.Formatter):
    """Structured JSON formatter for AWS CloudWatch compatibility."""
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created).astimezone().isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "request_id": getattr(record, "request_id", get_request_id()),
            "component": getattr(record, "component", record.name),
            "kind": getattr(record, "kind", "log"),
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "funcName": record.funcName,
            "lineNo": record.lineno,
        }
        
        # Add exception info if any
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        data = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED_LOG_RECORD_ATTRS and not key.startswith("_")
        }
        if data:
            log_data["data"] = data
            
        return json.dumps(log_data)


def setup_logging() -> None:
    """Setup logging configuration using settings."""
    global _logging_configured
    
    # Only configure once
    if _logging_configured:
        return
        
    from . import settings
    """Configure logging with both file and console handlers."""
    # Create logs directory if it doesn't exist
    log_path = Path(settings.log_file)
    log_path.parent.mkdir(exist_ok=True)
    
    # Get log level
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    
    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Clear existing handlers to avoid duplicates
    root_logger.handlers.clear()
    
    # Create formatters
    json_formatter = JSONFormatter()
    simple_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # File handler with rotation (Now using JSON structured logging)
    file_handler = logging.handlers.RotatingFileHandler(
        filename=settings.log_file,
        maxBytes=settings.log_max_size_mb * 1024 * 1024,  # Convert MB to bytes
        backupCount=settings.log_backup_count,
        encoding='utf-8'
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(json_formatter)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(simple_formatter if not settings.debug else json_formatter)
    
    # Add handlers to root logger
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Mark as configured
    _logging_configured = True
    
    # Log setup completion (only once)
    logger = logging.getLogger(__name__)
    logger.info(f"Structured JSON Logging configured: level={settings.log_level.upper()}, file={settings.log_file}")
    logger.info(f"Log rotation: {settings.log_max_size_mb}MB max, {settings.log_backup_count} backups")
