import asyncio
from config.logging import setup_logging
from tools.generate_meeting_details import generate_meeting_details
import os

setup_logging()

async def main():
    email_context = "Hey, I'd like to meet tomorrow to discuss the proposal."
    sender_email = "test@example.com"
    staff_availability = "Monday-Friday 9AM-5PM EST"
    staff_timezone = "America/New_York"
    
    print("Generating meeting details...")
    # generate_meeting_details is also a FunctionTool, so we access its function or use it directly?
    # Wait, in email_sender.py, the tools are passed to an Agent.
    # To test, we can just run the underlying function if we want.
    if hasattr(generate_meeting_details, 'function'):
        result = await generate_meeting_details.function(
            email_context=email_context,
            sender_email=sender_email,
            staff_availability=staff_availability,
            staff_timezone=staff_timezone
        )
        print(f"Result: {result}")
    else:
        print("Cannot call generate_meeting_details directly")

if __name__ == "__main__":
    asyncio.run(main())
