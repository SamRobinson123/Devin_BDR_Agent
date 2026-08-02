from routing import route_by_intent


def test_route_returns_intent_value():
    assert route_by_intent({"intent": "find_leads"}) == "find_leads"
    assert route_by_intent({"intent": "enrich_leads"}) == "enrich_leads"
    assert route_by_intent({"intent": "clarify"}) == "clarify"
