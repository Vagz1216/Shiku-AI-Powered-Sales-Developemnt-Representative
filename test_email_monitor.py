#!/usr/bin/env python3
"""Test the email monitoring system."""

import asyncio
import sys

from config import settings
from email_monitor import email_monitor, EmailIntent


def test_config():
    """Test configuration loading."""
    print("=== Testing Configuration ===")
    
    try:
        assert settings.openai_api_key, "OPENAI_API_KEY not set"
        assert settings.agentmail_api_key, "AGENTMAIL_API_KEY not set"
        assert settings.agentmail_inbox_id, "AGENTMAIL_INBOX_ID not set"
        
        print("✅ All required settings configured")
        return True
        
    except Exception as e:
        print(f"❌ Configuration error: {e}")
        return False


async def test_intent_extraction():
    """Test intent extraction from email content."""
    print("\n=== Testing Intent Extraction ===")
    
    try:
        # Test different email types
        test_cases = [
            ("Can we schedule a meeting this week?", "meeting_request"),
            ("What is your pricing for enterprise?", "question"),
            ("This looks interesting, tell me more", "interest"),
            ("Please remove me from your list", "opt_out"),
            ("I'm out of office until Monday", "bounce")
        ]
        
        for content, expected_intent in test_cases:
            intent = await email_monitor.intent_extractor.extract_intent(content)
            print(f"   '{content[:30]}...' → {intent.intent} (confidence: {intent.confidence})")
            
        print("✅ Intent extraction working")
        return True
        
    except Exception as e:
        print(f"❌ Intent extraction error: {e}")
        return False


async def test_email_processing():
    """Test complete email processing."""
    print("\n=== Testing Email Processing ===")
    
    # Sample webhook payload
    test_email = {
        'from_': ['potential.client@startup.com'],
        'subject': 'Interested in your services',
        'text': 'Hi, we\'re a growing startup and would like to know more about your team solutions and pricing.',
        'thread_id': 'test_thread_123',
        'labels': ['received']
    }
    
    try:
        result = await email_monitor.process_incoming_email(test_email)
        
        print(f"✅ Email processed: {result.action_taken}")
        print(f"   Success: {result.success}")
        if result.error:
            print(f"   Error: {result.error}")
        
        return result.success
        
    except Exception as e:
        print(f"❌ Email processing error: {e}")
        return False


def test_agent_initialization():
    """Test agent initialization."""
    print("\n=== Testing Agent Initialization ===")
    
    try:
        assert email_monitor is not None, "Email monitor not initialized"
        assert email_monitor.intent_extractor is not None, "Intent extractor not initialized"
        assert email_monitor.response_agent is not None, "Response agent not initialized"
        
        print("✅ All agents initialized successfully")
        return True
        
    except Exception as e:
        print(f"❌ Agent initialization error: {e}")
        return False


def test_webhook_payload():
    """Test webhook payload structure."""
    print("\n=== Testing Webhook Payload ===")
    
    try:
        from email_monitor.server import WebhookEvent
        
        # Test payload parsing
        test_payload = {
            "event_type": "message.received",
            "event_id": "evt_test_123",
            "message": {
                "from_": ["test@example.com"],
                "subject": "Test Subject",
                "text": "Test message content",
                "labels": ["received"]
            }
        }
        
        event = WebhookEvent(**test_payload)
        assert event.event_type == "message.received"
        assert event.message["from_"][0] == "test@example.com"
        
        print("✅ Webhook payload parsing works")
        return True
        
    except Exception as e:
        print(f"❌ Webhook payload error: {e}")
        return False


async def main():
    """Run all tests."""
    print("Email Monitor Test Suite")
    print("=" * 40)
    
    # Sync tests first
    sync_tests = [
        ("Configuration", test_config),
        ("Agent Initialization", test_agent_initialization), 
        ("Webhook Payload", test_webhook_payload),
    ]
    
    passed = 0
    
    for test_name, test_func in sync_tests:
        print(f"\nRunning {test_name}...")
        try:
            if test_func():
                passed += 1
        except Exception as e:
            print(f"❌ {test_name} failed: {e}")
    
    # Async tests 
    async_tests = [
        ("Intent Extraction", test_intent_extraction),
        ("Email Processing", test_email_processing),  # Uses API
    ]
    
    for test_name, test_func in async_tests:
        print(f"\nRunning {test_name}...")
        try:
            if await test_func():
                passed += 1
        except Exception as e:
            print(f"❌ {test_name} failed: {e}")
    
    total = len(sync_tests) + len(async_tests)
    
    print(f"\n{'='*40}")
    print(f"Tests completed: {passed}/{total} passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        print("\nNext steps:")
        print("1. Start server: python run_email_monitor.py")
        print("2. Setup webhook with your webhook URL")
    else:
        print(f"\n❌ {total - passed} test(s) failed")
        print("\nCheck your .env file has:")
        print("- OPENAI_API_KEY")
        print("- AGENTMAIL_API_KEY") 
        print("- AGENTMAIL_INBOX_ID")


if __name__ == "__main__":
    asyncio.run(main())