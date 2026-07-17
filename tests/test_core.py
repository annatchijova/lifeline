from lifeline.core import IncidentRequest, Resource, Route, Shelter, plan_response


def _routes():
    return [
        Route("boat-base", "north-bank", 11, True),
        Route("north-bank", "shelter-a", 8, True),
        Route("ambulance-base", "east-bank", 9, True),
        Route("east-bank", "shelter-a", 12, True),
        Route("boat-base", "east-bank", 30, False),
    ]


def test_plan_is_ordered_and_respects_hard_constraints():
    plan = plan_response(
        [
            IncidentRequest("family-east", 3, 4, True, "east-bank", "shelter-a"),
            IncidentRequest("family-north", 4, 5, False, "north-bank", "shelter-a"),
        ],
        [
            Resource("boat-02", "boat", 5, True, False, "boat-base"),
            Resource("ambulance-01", "ambulance", 3, True, True, "ambulance-base"),
        ],
        [Shelter("shelter-a", "shelter-a", 7, True)],
        _routes(),
    )

    assert [item.request_id for item in plan] == ["family-north", "family-east"]
    assert plan[0].status == "PROPOSED"
    assert plan[0].resource_id == "boat-02"
    assert plan[1].status == "PROPOSED"
    assert plan[1].resource_id == "ambulance-01"
    assert plan[1].eta_minutes == 21
    assert "human approval required" in plan[0].reasons


def test_unreachable_or_capacity_constrained_requests_need_human_review():
    plan = plan_response(
        [IncidentRequest("family-east", 4, 5, False, "east-bank", "shelter-a")],
        [Resource("boat-02", "boat", 5, True, False, "boat-base")],
        [Shelter("shelter-a", "shelter-a", 2, True)],
        _routes(),
    )

    assert plan[0].status == "NEEDS_HUMAN_REVIEW"
    assert plan[0].resource_id is None
    assert "no reachable destination shelter capacity" in plan[0].reasons


def test_audit_hash_is_deterministic():
    args = (
        [IncidentRequest("family-north", 4, 5, False, "north-bank", "shelter-a")],
        [Resource("boat-02", "boat", 5, True, False, "boat-base")],
        [Shelter("shelter-a", "shelter-a", 7, True)],
        _routes(),
    )
    assert plan_response(*args)[0].audit_hash == plan_response(*args)[0].audit_hash


def test_planner_never_substitutes_a_different_destination_shelter():
    plan = plan_response(
        [IncidentRequest("family-east", 3, 5, False, "east-bank", "shelter-a")],
        [Resource("ambulance-01", "ambulance", 3, True, True, "ambulance-base")],
        [
            Shelter("shelter-a", "shelter-a", 2, True),
            Shelter("shelter-b", "shelter-b", 10, True),
        ],
        [
            Route("ambulance-base", "east-bank", 9, True),
            Route("east-bank", "shelter-a", 12, True),
            Route("east-bank", "shelter-b", 1, True),
        ],
    )

    assert plan[0].status == "NEEDS_HUMAN_REVIEW"
    assert plan[0].shelter_id is None
    assert "no reachable destination shelter capacity" in plan[0].reasons
