#!/usr/bin/env python3
"""Setup instructions for AgentMail webhook configuration."""

import argparse


def show_setup_instructions():
    """Show webhook setup instructions."""
    print("🔗 AgentMail Webhook Setup Instructions")
    print("=" * 40)
    print()
    print("1. Log into your AgentMail dashboard")
    print("2. Navigate to Settings → Webhooks")
    print("3. Click 'Add Webhook'")
    print("4. Configure:")
    print(f"   • URL: https://your-domain.com/webhook")
    print(f"   • Events: message.received") 
    print(f"   • Inbox: Select your inbox")
    print("5. Save the webhook")
    print()
    print("💡 For local development:")
    print("   • Use ngrok: ngrok http 8000")
    print("   • Then use: https://abc123.ngrok.io/webhook")
    print()
    print("✅ Once configured, start the server:")
    print("   python run_email_monitor.py")


def show_ngrok_instructions():
    """Show ngrok setup instructions."""
    print("🌐 Local Development with Ngrok")
    print("=" * 32)
    print()
    print("1. Install ngrok: https://ngrok.com/download")
    print("2. Start your email monitor server:")
    print("   python run_email_monitor.py")
    print("3. In another terminal, start ngrok:")
    print("   ngrok http 8000")
    print("4. Copy the HTTPS URL (e.g., https://abc123.ngrok.io)")
    print("5. In AgentMail dashboard, set webhook URL to:")
    print("   https://abc123.ngrok.io/webhook")
    print()
    print("🔥 Your webhook is now ready for testing!")


def main():
    """Main CLI interface."""
    parser = argparse.ArgumentParser(description="AgentMail Webhook Setup Guide")
    parser.add_argument(
        "command", 
        nargs="?",
        choices=["setup", "ngrok"], 
        default="setup",
        help="Show setup instructions (setup) or ngrok guide (ngrok)"
    )
    
    args = parser.parse_args()
    
    if args.command == "ngrok":
        show_ngrok_instructions()
    else:
        show_setup_instructions()


if __name__ == "__main__":
    main()