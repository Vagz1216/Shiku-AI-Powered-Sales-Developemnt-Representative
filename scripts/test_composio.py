
import asyncio
import logging
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config.logging import setup_logging
from tools.google_calendar import create_google_meeting

async def test_composio():
    setup_logging()
    logger = logging.getLogger(__name__)
    
    print("\n--- Testing Composio Google Calendar Integration ---")
    
    # Simple test data
    attendees = ["test@example.com"]
    subject = "Composio Connection Test"
    start_time = "2026-05-01 10:00"
    duration = 15
    description = "Testing if Composio API key is working correctly."
    
    try:
        print(f"Attempting to create a test meeting at {start_time}...")
        # Access the underlying function of the @function_tool
        result = await create_google_meeting.__call__(
            attendees=attendees,
            subject=subject,
            start_time=start_time,
            duration_minutes=duration,
            description=description
        )
        
        if result.success:
            print(f"\n✅ SUCCESS!")
            print(f"Meeting Subject: {result.subject}")
            print(f"Meeting Link: {result.meeting_link}")
            print(f"Start Time: {result.start_time}")
        else:
            print(f"\n❌ FAILED")
            print(f"Error: {result.error}")
            
    except Exception as e:
        print(f"\n💥 CRITICAL ERROR during test: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_composio())
