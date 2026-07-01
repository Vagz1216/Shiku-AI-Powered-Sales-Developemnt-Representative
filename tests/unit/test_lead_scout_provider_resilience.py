import asyncio

import httpx

from config import settings
from outreach.lead_scout import agent as scout_agent
from outreach.lead_scout.discoverers.base import DiscoveredLead, ProviderFailure, clear_provider_cooldowns
from outreach.lead_scout.discoverers.apollo import ApolloDiscoverer
from outreach.lead_scout.discoverers.pdl import PeopleDataLabsDiscoverer
from outreach.lead_scout.icp_generator import ICPParameters


class QuotaDiscoverer:
    def __init__(self):
        self.calls = 0

    async def search_leads(self, icp_params, limit=50):
        self.calls += 1
        raise ProviderFailure("quota_exhausted", "Provider credits exhausted.", user_visible=True)


class GoodDiscoverer:
    async def search_leads(self, icp_params, limit=50):
        return [
            DiscoveredLead(
                name="Ava Revenue",
                email="ava@example.com",
                company="ExampleCo",
                job_title="VP of Sales",
                discovery_source="good",
            )
        ]


def _agent_with(discoverers):
    agent = scout_agent.LeadScoutAgent.__new__(scout_agent.LeadScoutAgent)
    agent.organization_id = 1
    agent.discoverers = discoverers
    agent.signal_enricher = None
    return agent


async def _fake_icp(**kwargs):
    return ICPParameters(
        job_titles=["VP of Sales"],
        industries=["Software"],
        company_size_ranges=["51,200"],
        locations=["United States"],
        keywords=["sales"],
        seniority_levels=["vp"],
        rationale="test",
    )


def test_discovery_returns_degraded_status_after_provider_failure(monkeypatch):
    clear_provider_cooldowns()
    monkeypatch.setattr(scout_agent, "generate_icp_from_campaign", _fake_icp)
    monkeypatch.setattr(settings, "lead_scout_provider_cooldown_seconds", 60)

    failing = QuotaDiscoverer()
    agent = _agent_with([failing, GoodDiscoverer()])

    result = asyncio.run(agent.run_discovery_job(1, {"name": "Campaign"}, limit=10))

    assert result["status"] == "COMPLETED"
    assert result["degraded"] is True
    assert result["provider_statuses"][0]["status"] == "failed"
    assert result["provider_statuses"][0]["reason"] == "quota_exhausted"
    assert result["provider_statuses"][1]["status"] == "used"
    assert result["candidates"][0]["email"] == "ava@example.com"


def test_non_retryable_provider_failure_enters_cooldown(monkeypatch):
    clear_provider_cooldowns()
    monkeypatch.setattr(scout_agent, "generate_icp_from_campaign", _fake_icp)
    monkeypatch.setattr(settings, "lead_scout_provider_cooldown_seconds", 60)

    first_failing = QuotaDiscoverer()
    asyncio.run(_agent_with([first_failing, GoodDiscoverer()]).run_discovery_job(1, {"name": "Campaign"}, limit=10))

    second_failing = QuotaDiscoverer()
    result = asyncio.run(_agent_with([second_failing, GoodDiscoverer()]).run_discovery_job(1, {"name": "Campaign"}, limit=10))

    assert second_failing.calls == 0
    assert result["provider_statuses"][0]["status"] == "skipped"
    assert result["provider_statuses"][0]["reason"] == "quota_exhausted"


def test_discovery_skips_icp_generation_when_all_providers_are_in_cooldown(monkeypatch):
    clear_provider_cooldowns()
    monkeypatch.setattr(scout_agent, "generate_icp_from_campaign", _fake_icp)
    monkeypatch.setattr(settings, "lead_scout_provider_cooldown_seconds", 60)

    asyncio.run(_agent_with([QuotaDiscoverer()]).run_discovery_job(1, {"name": "Campaign"}, limit=10))

    async def fail_if_called(**kwargs):
        raise AssertionError("ICP generation should not run when all providers are unavailable")

    monkeypatch.setattr(scout_agent, "generate_icp_from_campaign", fail_if_called)

    result = asyncio.run(_agent_with([QuotaDiscoverer()]).run_discovery_job(1, {"name": "Campaign"}, limit=10))

    assert result["status"] == "FAILED"
    assert result["error"] == "All lead discovery providers are temporarily unavailable."
    assert result["icp_used"] is None
    assert result["provider_statuses"][0]["status"] == "skipped"


def test_mock_discoverer_is_included_last_for_debug_demo(monkeypatch):
    monkeypatch.setattr(settings, "apollo_api_key", "apollo-key")
    monkeypatch.setattr(settings, "pdl_api_key", "pdl-key")
    monkeypatch.setattr(settings, "debug", True)
    monkeypatch.setattr(settings, "lead_scout_mock_fallback_enabled", False)

    discoverers = scout_agent._get_discoverers()

    assert [type(discoverer).__name__ for discoverer in discoverers] == [
        "ApolloDiscoverer",
        "PeopleDataLabsDiscoverer",
        "MockDiscoverer",
    ]


def test_mock_discoverer_stays_disabled_for_production_without_flag(monkeypatch):
    monkeypatch.setattr(settings, "apollo_api_key", None)
    monkeypatch.setattr(settings, "pdl_api_key", None)
    monkeypatch.setattr(settings, "debug", False)
    monkeypatch.setattr(settings, "lead_scout_mock_fallback_enabled", False)

    assert scout_agent._get_discoverers() == []


def test_credit_exposure_requires_approval_for_pdl(monkeypatch):
    clear_provider_cooldowns()
    monkeypatch.setattr(settings, "pdl_max_search_size", 7)
    agent = _agent_with([PeopleDataLabsDiscoverer(api_key="pdl-test"), GoodDiscoverer()])

    estimate = agent.estimate_credit_exposure(limit=50)

    assert estimate["requires_approval"] is True
    assert estimate["estimated_max_credits"] == 7
    assert estimate["provider_statuses"][0]["name"] == "PeopleDataLabsDiscoverer"
    assert estimate["provider_statuses"][0]["credit_consuming"] is True


def test_credit_exposure_does_not_require_approval_for_non_paid_mock_path():
    clear_provider_cooldowns()
    agent = _agent_with([GoodDiscoverer()])

    estimate = agent.estimate_credit_exposure(limit=50)

    assert estimate["requires_approval"] is False
    assert estimate["estimated_max_credits"] == 0


def test_pdl_402_maps_to_quota_exhausted_failure():
    response = httpx.Response(402, json={"error": "payment required"})
    failure = PeopleDataLabsDiscoverer(api_key="pdl-test")._failure_from_response(response)

    assert failure.code == "quota_exhausted"
    assert failure.retryable is False
    assert failure.user_visible is True


def test_apollo_422_maps_to_payload_failure():
    response = httpx.Response(422, json={"message": "invalid field"})
    failure = ApolloDiscoverer(api_key="apollo-test")._failure_from_response(response)

    assert failure.code == "provider_payload_invalid"
    assert failure.retryable is False
    assert failure.user_visible is False


def test_pdl_query_caps_terms_and_requires_email():
    query = PeopleDataLabsDiscoverer(api_key="pdl-test")._build_query(
        {
            "job_titles": ["VP of Sales", "Head of Growth", "Founder", "CEO", "Extra"],
            "industries": ["Software"],
            "locations": ["United States"],
            "seniority_levels": ["vp"],
        }
    )

    must = query["bool"]["must"]
    should = query["bool"]["should"]

    assert must[0]["bool"]["minimum_should_match"] == 1
    assert {"exists": {"field": "work_email"}} in must[0]["bool"]["should"]
    assert {"terms": {"job_title_levels": ["vp"]}} in must
    assert len([clause for clause in should if "match_phrase" in clause and "job_title" in clause["match_phrase"]]) == 4
