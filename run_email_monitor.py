#!/usr/bin/env python3
"""Run the email monitoring webhook server."""

import argparse
import logging
import sys
import uvicorn

from email_monitor import app


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Email Monitor Webhook Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to") 
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--log-level", default="INFO", help="Log level")
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)
    logger.info(f"Starting Email Monitor on {args.host}:{args.port}")
    
    # Start server
    uvicorn.run(
        "email_monitor:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level.lower()
    )


if __name__ == "__main__":
    main()