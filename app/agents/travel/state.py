from app.agents.contracts import AgentCoordinationState


class TravelState(AgentCoordinationState, total=False):
    """Travel-agent state; only coordination fields are visible to the root."""

    travel_action: str
    travel_stage: str
    plan_id: str
    trip_request: dict
    missing_fields: list[str]
    research_plan: list[dict]
    research_documents: list[dict]
    research_approved: bool | None
    research_round: int
    attraction_candidates: list[dict]
    hotel_candidates: list[dict]
    weather_result: dict
    itinerary: list[dict]
    budget: dict
    alternatives: list[dict]
    warnings: list[dict]
    sources: list[dict]
    travel_plan: dict
    revision_patch: dict
    revision_error: str | None
