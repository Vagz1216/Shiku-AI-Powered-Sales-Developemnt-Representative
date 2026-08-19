from utils.email_deliverability import normalize_outreach_subject


def test_normalize_outreach_subject_replaces_spammy_stayez_subject():
    assert (
        normalize_outreach_subject(
            "Following up on StayEZ partnership opportunities",
            company_name="Stayez Homes",
        )
        == "Rates and media for StayEZ"
    )


def test_normalize_outreach_subject_keeps_specific_safe_subject():
    assert (
        normalize_outreach_subject(
            "Rates and media for Amboseli Serena",
            company_name="StayEZ",
        )
        == "Rates and media for Amboseli Serena"
    )
