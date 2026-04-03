import asyncio
import logging
import sys
from pathlib import Path

# Allow importing from root
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from utils.model_fallback import run_agent_with_fallback
from config.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

async def main():
    print("--- Testing Model Fallback ---")
    
    instructions = "You are a helpful assistant that responds in exactly 5 words."
    prompt = "Tell me something about AI."
    
    try:
        print(f"Attempting to run agent with fallback...")
        result = await run_agent_with_fallback(
            name="TestFallbackAgent",
            instructions=instructions,
            prompt=prompt,
            temperature=0.7,
            max_tokens=20
        )
        print(f"\n✅ Success! Result: {result}")
        
    except Exception as e:
        print(f"\n❌ Failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
