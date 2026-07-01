import logging
from typing import Dict, Any, List
from .icp_generator import generate_icp_from_campaign
from config.settings import settings
from .discoverers.base import ProviderFailure, provider_cooldown, remember_provider_failure

def _get_discoverers():
    """Return a list of available discoverers based on configured API keys, ordered by priority."""
    discoverers = []
    
    if getattr(settings, "apollo_api_key", None):
        from .discoverers.apollo import ApolloDiscoverer
        discoverers.append(ApolloDiscoverer(api_key=settings.apollo_api_key))
        
    if getattr(settings, "pdl_api_key", None):
        from .discoverers.pdl import PeopleDataLabsDiscoverer
        discoverers.append(PeopleDataLabsDiscoverer(api_key=settings.pdl_api_key))
        
    if getattr(settings, "lead_scout_mock_fallback_enabled", False) or getattr(settings, "debug", False):
        from .discoverers.mock import MockDiscoverer
        discoverers.append(MockDiscoverer())
    
    return discoverers

logger = logging.getLogger(__name__)

class LeadScoutAgent:
    """Orchestrates the discovery and qualification of new leads for a campaign."""
    
    def __init__(self, organization_id: int):
        self.organization_id = organization_id
        self.discoverers = _get_discoverers()
        self.signal_enricher = None
        if getattr(settings, "tavily_api_key", None):
            from .discoverers.tavily import TavilySignalEnricher
            self.signal_enricher = TavilySignalEnricher(api_key=settings.tavily_api_key)
        discoverer_names = [type(d).__name__ for d in self.discoverers]
        logger.info(
            "LeadScoutAgent initialized with discoverer chain: %s; Tavily enrichment: %s",
            discoverer_names,
            "enabled" if self.signal_enricher else "disabled",
        )

    def _provider_status(self, name: str, status: str, **details: Any) -> Dict[str, Any]:
        payload = {"name": name, "status": status}
        payload.update({key: value for key, value in details.items() if value is not None})
        return payload

    def _available_discoverers(self) -> tuple[List[Any], List[Dict[str, Any]]]:
        available = []
        provider_statuses: List[Dict[str, Any]] = []
        for discoverer in self.discoverers:
            discoverer_name = type(discoverer).__name__
            cooldown = provider_cooldown(discoverer_name)
            if cooldown:
                provider_statuses.append(
                    self._provider_status(
                        discoverer_name,
                        "skipped",
                        reason=cooldown.code,
                        message=cooldown.message,
                    )
                )
                continue
            available.append(discoverer)
        return available, provider_statuses

    def estimate_credit_exposure(self, limit: int = 50) -> Dict[str, Any]:
        """Estimate max paid discovery exposure before running an LLM or provider call."""
        available_discoverers, provider_statuses = self._available_discoverers()
        provider_estimates: List[Dict[str, Any]] = list(provider_statuses)
        max_credits = 0
        requires_approval = False

        for discoverer in available_discoverers:
            discoverer_name = type(discoverer).__name__
            if discoverer_name == "PeopleDataLabsDiscoverer":
                estimated = min(limit, getattr(settings, "pdl_max_search_size", 10), 100)
                max_credits += estimated
                requires_approval = True
                provider_estimates.append(
                    self._provider_status(
                        discoverer_name,
                        "available",
                        credit_consuming=True,
                        estimated_max_credits=estimated,
                        message="PDL Person Search can consume one credit per successful profile returned.",
                    )
                )
            else:
                provider_estimates.append(
                    self._provider_status(
                        discoverer_name,
                        "available",
                        credit_consuming=False,
                        estimated_max_credits=0,
                    )
                )

        return {
            "requires_approval": requires_approval,
            "estimated_max_credits": max_credits,
            "provider_statuses": provider_estimates,
        }
        
    async def run_discovery_job(self, campaign_id: int, campaign_context: Dict[str, Any], limit: int = 50) -> Dict[str, Any]:
        """
        Run the full discovery pipeline for a campaign:
        1. Generate ICP from campaign context
        2. Search discoverers sequentially for leads matching the ICP
        3. Import qualified leads directly into the campaign
        """
        logger.info(f"Starting Lead Scout for campaign {campaign_id}")
        provider_statuses: List[Dict[str, Any]] = []

        if not self.discoverers:
            logger.warning("No lead discovery providers are configured.")
            return {
                "status": "FAILED",
                "error": "No lead discovery providers are configured.",
                "provider_statuses": provider_statuses,
                "candidates_found": 0,
                "leads_imported": 0,
                "icp_used": None,
            }

        available_discoverers, provider_statuses = self._available_discoverers()
        if not available_discoverers:
            logger.warning("All lead discovery providers are unavailable due to active cooldowns.")
            return {
                "status": "FAILED",
                "error": "All lead discovery providers are temporarily unavailable.",
                "provider_statuses": provider_statuses,
                "candidates_found": 0,
                "leads_imported": 0,
                "icp_used": None,
            }

        # 1. Generate ICP only after at least one provider can run.
        logger.info("Generating ICP parameters...")
        icp = await generate_icp_from_campaign(
            campaign_name=campaign_context.get("name", "Unknown Campaign"),
            value_proposition=campaign_context.get("value_proposition", ""),
            cta=campaign_context.get("cta", ""),
        )
        logger.info(f"Generated ICP targeting: {icp.job_titles} in {icp.industries}")
        
        # 2. Discover Leads
        logger.info(f"Searching for leads (limit={limit})...")
        candidates = []
        last_error = None
        
        for discoverer in available_discoverers:
            discoverer_name = type(discoverer).__name__
            logger.info(f"Trying discoverer: {discoverer_name}")
            try:
                candidates = await discoverer.search_leads(icp.model_dump(), limit=limit)
                if candidates:
                    logger.info(f"{discoverer_name} successfully found {len(candidates)} candidates.")
                    provider_statuses.append(
                        self._provider_status(discoverer_name, "used", candidates_found=len(candidates))
                    )
                    break
                else:
                    logger.info(f"{discoverer_name} returned 0 candidates. Falling back to the next discoverer...")
                    provider_statuses.append(self._provider_status(discoverer_name, "empty", candidates_found=0))
            except ProviderFailure as e:
                logger.warning(
                    "Discoverer %s failed with classified error %s: %s. Falling back...",
                    discoverer_name,
                    e.code,
                    e,
                )
                remember_provider_failure(
                    discoverer_name,
                    e,
                    getattr(settings, "lead_scout_provider_cooldown_seconds", 900),
                )
                provider_statuses.append(
                    self._provider_status(
                        discoverer_name,
                        "failed",
                        reason=e.code,
                        retryable=e.retryable,
                        user_visible=e.user_visible,
                        message=str(e),
                    )
                )
                last_error = e
            except Exception as e:
                logger.exception("Discoverer %s failed unexpectedly. Falling back...", discoverer_name)
                provider_statuses.append(
                    self._provider_status(
                        discoverer_name,
                        "failed",
                        reason="unexpected_error",
                        retryable=True,
                        user_visible=False,
                        message=str(e),
                    )
                )
                last_error = e
                
        if not candidates:
            if last_error:
                return {
                    "status": "FAILED",
                    "error": "No lead discovery provider returned candidates.",
                    "provider_statuses": provider_statuses,
                    "candidates_found": 0,
                    "leads_imported": 0,
                    "icp_used": icp.model_dump(),
                }
            else:
                return {
                    "status": "COMPLETED",
                    "degraded": bool(provider_statuses),
                    "provider_statuses": provider_statuses,
                    "candidates_found": 0,
                    "leads_imported": 0,
                    "icp_used": icp.model_dump(),
                }
            
        logger.info(f"Found {len(candidates)} candidates.")

        if self.signal_enricher:
            candidates = await self.signal_enricher.enrich_leads(candidates)
        
        # Format the leads for review instead of auto-importing
        formatted_candidates: List[Dict[str, Any]] = []
        for candidate in candidates:
            if not candidate.email:
                continue # Skip leads without email
            formatted_candidates.append(candidate.to_import_payload(campaign_id))
                
        logger.info(f"Discovery job complete. Returning {len(formatted_candidates)} candidates for review.")
        
        return {
            "status": "COMPLETED",
            "degraded": any(status["status"] in {"failed", "skipped"} for status in provider_statuses),
            "provider_statuses": provider_statuses,
            "candidates_found": len(candidates),
            "candidates": formatted_candidates,
            "leads_imported": 0,  # Import is now a separate manual step
            "icp_used": icp.model_dump()
        }
