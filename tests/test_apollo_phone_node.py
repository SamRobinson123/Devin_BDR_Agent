from graph import apollo_phone_node


def test_uses_phone_already_found_by_web_search():
    state = {"enriched": [{"first_name": "Jane", "last_name": "Doe",
                            "domain": "acme.com", "phone": "+1-555-0100"}]}
    result = apollo_phone_node(state)
    assert result["enriched"][0]["phone"] == "+1-555-0100"
    assert result["enriched"][0]["phone_status"] == "found"


def test_marks_not_found_when_no_phone_surfaced():
    state = {"enriched": [{"first_name": "No", "last_name": "One", "domain": "x.com"}]}
    result = apollo_phone_node(state)
    assert result["enriched"][0]["phone"] is None
    assert result["enriched"][0]["phone_status"] == "not_found"
