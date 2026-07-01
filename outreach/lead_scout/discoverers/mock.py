import random
from typing import List, Dict, Any
from .base import BaseDiscoverer, DiscoveredLead
import logging

logger = logging.getLogger(__name__)

# Realistic mock data pools
FIRST_NAMES = ["James", "Sarah", "Michael", "Emily", "David", "Jessica", "Robert", "Ashley", "William", "Jennifer", "John", "Amanda", "Thomas", "Melissa", "Christopher"]
LAST_NAMES  = ["Chen", "Patel", "Williams", "Johnson", "Smith", "Brown", "Davis", "Miller", "Wilson", "Moore", "Taylor", "Anderson", "Jackson", "White", "Harris"]
COMPANIES   = ["Acme SaaS", "Velocity Growth", "NexGen Labs", "Pinnacle Digital", "CloudWave", "Horizon Tech", "Apex Solutions", "Synergy AI", "TechBridge", "DataFlow Inc"]
TITLES      = ["VP of Sales", "Head of Sales", "Director of Revenue", "Chief Revenue Officer", "Sales Manager", "Head of Growth", "Founder & CEO", "Co-Founder & COO"]
SENIORITIES = ["vp", "director", "c_suite", "manager"]
INDUSTRIES  = ["Software / SaaS", "FinTech", "EdTech", "HealthTech", "E-Commerce", "MarketingTech"]
LOCATIONS   = ["San Francisco, CA", "New York, NY", "Austin, TX", "London, UK", "Nairobi, Kenya", "Lagos, Nigeria", "Bangalore, India"]
COMPANY_SIZES = ["1-10", "11-50", "51-200", "201-500"]
PAIN_POINTS = [
    "Needs more qualified pipeline without expanding SDR headcount",
    "Low reply rates from outbound sequences",
    "Revenue team lacks clean intent and account research",
    "Manual lead qualification is slowing follow-up",
    None,
    None,
]
RECENT_ACTIVITIES = [
    "Just announced a Series A funding round of $5M",
    "Posted about scaling their sales team to 20+ reps",
    "Shared insights on improving outbound conversion rates",
    "Promoted to VP of Sales after 18 months as Director",
    "Spoke at SaaStr about building repeatable revenue",
    "Recently joined as the first sales hire at a Series A startup",
    None,  # Some leads have no recent activity
    None,
]

class MockDiscoverer(BaseDiscoverer):
    """
    A mock lead discoverer for development and testing.
    Returns realistic-looking leads based on ICP parameters without any external API calls.
    Replace this with ApolloDiscoverer (or another provider) once you have a paid API key.
    """

    async def search_leads(self, icp_params: Dict[str, Any], limit: int = 10) -> List[DiscoveredLead]:
        logger.info(f"[MockDiscoverer] Generating {limit} mock leads for ICP: {icp_params}")
        
        titles = icp_params.get("job_titles") or TITLES
        
        results = []
        used_emails = set()
        
        for _ in range(min(limit, 20)):
            first = random.choice(FIRST_NAMES)
            last  = random.choice(LAST_NAMES)
            company = random.choice(COMPANIES)
            
            # Generate a unique email
            email = f"{first.lower()}.{last.lower()}@{company.lower().replace(' ', '').replace('/', '')}.com"
            if email in used_emails:
                email = f"{first.lower()}.{last.lower()}{random.randint(1, 99)}@{company.lower().replace(' ', '').replace('/', '')}.com"
            used_emails.add(email)
            maybe_phone = None
            if random.random() > 0.5:
                maybe_phone = f"+1-555-{random.randint(100, 999)}-{random.randint(1000, 9999)}"
            
            lead = DiscoveredLead(
                name=f"{first} {last}",
                email=email,
                phone_number=maybe_phone,
                linkedin_url=f"https://linkedin.com/in/{first.lower()}-{last.lower()}-{random.randint(100,999)}",
                company=company,
                industry=random.choice(INDUSTRIES),
                pain_points=random.choice(PAIN_POINTS),
                job_title=random.choice(titles),
                seniority=random.choice(SENIORITIES),
                location=random.choice(LOCATIONS),
                company_size=random.choice(COMPANY_SIZES),
                company_website=f"https://www.{company.lower().replace(' ', '')}.com",
                company_description=f"{company} is a growing B2B software company focused on helping sales teams scale.",
                recent_activity=random.choice(RECENT_ACTIVITIES),
                discovery_source="mock"
            )
            results.append(lead)
        
        logger.info(f"[MockDiscoverer] Generated {len(results)} mock leads.")
        return results
