from services.inference.telemetry import InferenceTelemetry


def test_telemetry_records_retry_and_fallback():
    telemetry = InferenceTelemetry()

    telemetry.record(
        agent_name="reasoning_agent",
        task_type="recommendation_reasoning",
        provider="gemini",
        model="gemini-2.5-flash",
        retried=True,
        fell_back=True,
        status="success",
    )

    assert telemetry.events[0]["agent_name"] == "reasoning_agent"
    assert telemetry.events[0]["fell_back"] is True