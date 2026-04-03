#!/usr/bin/env python3
"""
Helper script to update a lead's email address for testing real email sends.
"""

import argparse
from sqlalchemy import select
from packages.db.models import Lead, CampaignLead, Campaign
from packages.db.session import get_session_factory

def main():
    parser = argparse.ArgumentParser(description="Update an existing lead to a real email address for testing.")
    parser.add_argument("email", help="The real email address you want to use for testing")
    parser.add_argument("--name", default="Real Tester", help="Name of the tester (optional)")
    parser.add_argument("--campaign", type=int, default=1, help="Campaign ID to ensure they are linked to (default: 1)")
    args = parser.parse_args()

    real_email = args.email
    tester_name = args.name
    campaign_id = args.campaign

    factory = get_session_factory()
    session = factory()

    try:
        # 1. Check if campaign exists
        campaign = session.scalar(select(Campaign).where(Campaign.id == campaign_id))
        if not campaign:
            print(f"❌ Campaign {campaign_id} not found.")
            return

        # 2. Check if the email already exists
        existing_lead = session.scalar(select(Lead).where(Lead.email == real_email))
        
        if existing_lead:
            print(f"Lead {real_email} already exists in the database (ID: {existing_lead.id}). Updating name and ensuring they are eligible...")
            existing_lead.name = tester_name
            existing_lead.email_opt_out = False
            existing_lead.touch_count = 0
            existing_lead.status = "NEW"
            lead_id = existing_lead.id
        else:
            # Let's just grab the first dummy lead (like alice@example.com) and update it
            # Or better yet, just create a new one to be safe.
            print(f"Creating a new lead for {real_email}...")
            new_lead = Lead(
                email=real_email,
                name=tester_name,
                status="NEW",
                email_opt_out=False,
                touch_count=0,
            )
            session.add(new_lead)
            session.flush() # get the ID
            lead_id = new_lead.id

        # 3. Ensure they are linked to the active campaign and eligible
        link = session.scalar(
            select(CampaignLead)
            .where(CampaignLead.campaign_id == campaign_id)
            .where(CampaignLead.lead_id == lead_id)
        )

        if link:
            print(f"Resetting campaign stats for {real_email} on Campaign {campaign_id}...")
            link.emails_sent = 0
            link.responded = False
            link.meeting_booked = False
        else:
            print(f"Linking {real_email} to Campaign {campaign_id}...")
            session.add(
                CampaignLead(
                    campaign_id=campaign_id,
                    lead_id=lead_id,
                    emails_sent=0,
                    responded=False,
                    meeting_booked=False,
                )
            )

        session.commit()
        print(f"✅ Success! {real_email} is now ready for outreach testing on Campaign {campaign_id}.")
        print(f"👉 Run: uv run python scripts/run_outreach.py --limit 1")

    except Exception as e:
        session.rollback()
        print(f"❌ Error: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    main()
