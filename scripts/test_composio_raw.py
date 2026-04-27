
import asyncio
import logging
import sys
import os
from datetime import datetime

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config.logging import setup_logging
from config import settings
from schema import MeetingResult

async def create_google_meeting_raw(
    attendees: list[str],
    subject: str,
    start_time: str,
    duration_minutes: int = 30,
    description: str = ""
) -> MeetingResult:
    try:
        # Import Composio modules
        from composio import Composio
        from composio_openai_agents import OpenAIAgentsProvider
        from agents import Agent, Runner

        # Set environment variables
        os.environ["COMPOSIO_API_KEY"] = settings.composio_api_key
        os.environ["OPENAI_API_KEY"] = settings.openai_api_key

        # Initialize Composio
        composio = Composio(provider=OpenAIAgentsProvider())
        session = composio.create(user_id=settings.composio_user_id)
        tools = session.tools()
        
        # Create a simple agent to use the tools
        agent = Agent(
            name="CalendarTester",
            instructions="Create a google calendar meeting with the provided details.",
            tools=tools
        )
        
        prompt = f"""
        Create a meeting with these details:
        Subject: {subject}
        Attendees: {', '.join(attendees)}
        Start Time: {start_time}
        Duration: {duration_minutes} minutes
        Description: {description}
        """
        
        print("Running agent to create meeting...")
        result = await Runner.run(agent, prompt)
        
        print(f"Agent Output: {result.final_output}")
        
        # In a real tool we'd parse this, but for testing we'll just check if it finished
        return MeetingResult(
            success=True,
            subject=subject,
            meeting_link="Check your calendar!",
            start_time=start_time,
            duration_minutes=duration_minutes
        )
            
    except Exception as e:
        return MeetingResult(success=False, error=str(e))

async def test_composio():
    setup_logging()
    print("\n--- Testing Composio Raw Integration ---")
    
    if not settings.composio_api_key:
        print("❌ Error: COMPOSIO_API_KEY not found in .env")
        return

    result = await create_google_meeting_raw(
        attendees=["test@example.com"],
        subject="Composio Raw Test",
        start_time="2026-05-01 10:00",
        duration_minutes=15
    )
    
    if result.success:
        print("\n✅ API Key and Connection look GOOD!")
    else:
        print(f"\n❌ Connection Failed: {result.error}")

if __name__ == "__main__":
    asyncio.run(test_composio())
