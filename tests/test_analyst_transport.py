"""Exercise the analyst's real SDK schema conversion without Gemini access."""

import asyncio
import json

import httpx
import pytest
from google.adk.models.llm_request import LlmRequest
from google.genai import types
from pydantic import ValidationError

from grant_navigator.agent import eligibility_analyst
from grant_navigator.eligibility import EligibilityDraft, RULE_IDS
from grant_navigator.model_client import BufferedGemini


def test_analyst_schema_reaches_http_and_response_parses_with_real_model_adapter():
    """Catch SDK-incompatible constraints before they break a live agent run."""
    calls = []
    expected = {
        "decisions": [{
            "opportunity_id": 363696,
            "requirements": [{
                "rule_id": "applicant_type",
                "status": "needs_verification",
                "reason": "The applicant category still needs source verification.",
                "profile_fields": ["organization_type"],
                "evidence_refs": [],
                "applicability": "uncertain",
            }],
            "summary": "No overall eligibility determination has been made.",
        }],
        "summary": "Synthetic response for offline transport validation.",
    }

    def handler(request):
        assert request.url.path.endswith(":generateContent")
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={
            "candidates": [{
                "content": {"role": "model", "parts": [{"text": json.dumps(expected)}]},
                "finishReason": "STOP",
            }],
        })

    async def scenario():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as async_client:
            with httpx.Client(transport=transport) as sync_client:
                template = eligibility_analyst.model
                assert isinstance(template, BufferedGemini)
                model = template.model_copy(update={
                    "client_kwargs": {
                        "api_key": "test-key-no-network",
                        "http_options": types.HttpOptions(
                            timeout=template.client_kwargs["http_options"].timeout,
                            httpx_client=sync_client,
                            httpx_async_client=async_client,
                        ),
                    },
                    "retry_options": template.retry_options.model_copy(update={
                        "initial_delay": 0, "max_delay": 0, "jitter": 0,
                    }),
                })
                request = LlmRequest(
                    model=model.model,
                    config=eligibility_analyst.generate_content_config.model_copy(deep=True),
                    contents=[types.Content(role="user", parts=[types.Part(text="Assess the supplied candidate facts.")])],
                )
                request.set_output_schema(eligibility_analyst.output_schema)
                try:
                    return [response async for response in model.generate_content_async(request)]
                finally:
                    await model.api_client.aio.aclose()
                    model.api_client.close()

    responses = asyncio.run(scenario())

    assert len(calls) == 1 and len(responses) == 1
    config = calls[0]["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    schema = config["responseSchema"]
    # Check the actual wire schema after the production compatibility filter
    # and SDK conversion. This verifies the known transport constraints; only
    # a live request can establish acceptance by the remote API.
    types.Schema.model_validate(schema)
    encoded_schema = json.dumps(schema)
    assert all(keyword not in encoded_schema for keyword in (
        "$ref", "exclusiveMinimum", "additionalProperties", "additional_properties",
    ))
    assert set(schema["properties"]) == {"decisions"}
    candidate = schema["properties"]["decisions"]["items"]
    assert set(candidate["properties"]) == {"opportunity_id", "requirements", "fit_evidence"}
    assert "opportunity_id" in candidate["required"]
    assert candidate["properties"]["opportunity_id"]["type"] == "INTEGER"
    assert candidate["properties"]["opportunity_id"]["minimum"] == 1
    requirement = candidate["properties"]["requirements"]["items"]
    assert set(requirement["properties"]["rule_id"]["enum"]) == set(RULE_IDS)
    assert set(requirement["properties"]["status"]["enum"]) == {"met", "not_met", "needs_verification"}
    citation = requirement["properties"]["evidence_refs"]["items"]
    assert set(citation["properties"]) == {"evidence_id", "quote"}
    assert set(citation["required"]) == {"evidence_id", "quote"}

    response = responses[0]
    assert response.finish_reason == types.FinishReason.STOP
    parsed = EligibilityDraft.model_validate_json(response.content.parts[0].text)
    assert parsed == EligibilityDraft.model_validate(expected)
    assert parsed.decisions[0].opportunity_id == 363696
    assert parsed.decisions[0].requirements[0].status == "needs_verification"
    # Removing an unsupported generation constraint must not weaken strict
    # application acceptance of the model's returned JSON.
    with pytest.raises(ValidationError, match="extra_forbidden"):
        EligibilityDraft.model_validate({**expected, "unexpected_field": True})
    nested_extra = json.loads(json.dumps(expected))
    nested_extra["decisions"][0]["requirements"][0]["unexpected_field"] = True
    with pytest.raises(ValidationError, match="extra_forbidden"):
        EligibilityDraft.model_validate(nested_extra)
