"""Exercise transient model failures through ADK without live API requests."""

import asyncio
import json

import httpx
import pytest
from google.adk.models.llm_request import LlmRequest
from google.genai import errors, types

from grant_navigator.agent import root_agent


def run_mock_model(statuses, calls, stream=False, payloads=None):
    def handler(request):
        assert request.url.path.endswith(":generateContent")
        calls.append(request)
        status = statuses[min(len(calls) - 1, len(statuses) - 1)]
        if status != 200:
            return httpx.Response(
                status,
                json={"error": {"code": status, "message": "Simulated failure"}},
            )
        body = (
            payloads[min(len(calls) - 1, len(payloads) - 1)]
            if payloads else {
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": "OK"}]},
                        "finishReason": "STOP",
                    }
                ]
            }
        )
        return httpx.Response(200, json=body)

    async def scenario():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as async_client:
            with httpx.Client(transport=transport) as sync_client:
                model = root_agent.model.model_copy(
                    update={
                        "client_kwargs": {
                            "api_key": "test-key-no-network",
                            "http_options": types.HttpOptions(
                                timeout=root_agent.model.client_kwargs["http_options"].timeout,
                                httpx_client=sync_client,
                                httpx_async_client=async_client,
                            ),
                        },
                        # Keep the production retry policy, without sleeping in tests.
                        "retry_options": root_agent.model.retry_options.model_copy(
                            update={"initial_delay": 0, "max_delay": 0, "jitter": 0}
                        ),
                    }
                )
                request = LlmRequest(
                    model=model.model,
                    contents=[types.Content(role="user", parts=[types.Part(text="Hello")])],
                )
                try:
                    return [response async for response in model.generate_content_async(request, stream=stream)]
                finally:
                    await model.api_client.aio.aclose()
                    model.api_client.close()

    return asyncio.run(scenario())


@pytest.mark.parametrize("stream", [False, True])
def test_recovers_after_two_503_responses(stream):
    calls = []
    responses = run_mock_model([503, 503, 200], calls, stream=stream)

    assert len(calls) == 3
    assert responses[-1].content.parts[0].text == "OK"
    assert calls[0].extensions["timeout"]["read"] == 20.0


@pytest.mark.parametrize("stream", [False, True])
def test_persistent_503_stops_after_three_attempts(stream):
    calls = []
    with pytest.raises(errors.ServerError):
        run_mock_model([503], calls, stream=stream)

    assert len(calls) == 3


@pytest.mark.parametrize("stream", [False, True])
def test_does_not_retry_permission_errors(stream):
    calls = []
    with pytest.raises(errors.ClientError):
        run_mock_model([403], calls, stream=stream)

    assert len(calls) == 1


def candidate(parts=None, finish_reason="STOP"):
    return {
        "candidates": [{
            "content": {"role": "model", "parts": parts or []},
            "finishReason": finish_reason,
        }]
    }


@pytest.mark.parametrize("stream", [False, True])
def test_empty_stop_retries_same_request_once_and_returns_text(stream, caplog):
    calls = []
    responses = run_mock_model(
        [200], calls, stream=stream,
        payloads=[candidate(), candidate([{"text": "Recovered answer"}])],
    )

    assert len(calls) == 2
    assert len(responses) == 1  # Do not expose the first empty turn to ADK.
    assert responses[0].content.parts[0].text == "Recovered answer"
    assert json.loads(calls[0].content) == json.loads(calls[1].content)
    assert "retrying the model request once" in caplog.text
    assert "Hello" not in caplog.text  # No prompt content in the application log.


@pytest.mark.parametrize("stream", [False, True])
def test_empty_stop_retries_before_returning_one_valid_tool_call(stream):
    calls = []
    responses = run_mock_model(
        [200], calls, stream=stream,
        payloads=[candidate(), candidate([{
            "functionCall": {"name": "search_grants", "args": {"keyword": "community"}}
        }])],
    )

    assert len(calls) == 2
    assert len(responses) == 1
    assert responses[0].get_function_calls()[0].name == "search_grants"


@pytest.mark.parametrize("stream", [False, True])
def test_persistent_empty_stop_stops_after_two_model_requests(stream, caplog):
    calls = []
    responses = run_mock_model([200], calls, stream=stream, payloads=[candidate()])

    assert len(calls) == 2
    assert len(responses) == 1
    assert responses[0].finish_reason == types.FinishReason.STOP
    assert not responses[0].content.parts
    assert "returning it to ADK" in caplog.text


@pytest.mark.parametrize("stream", [False, True])
def test_valid_tool_call_does_not_retry_or_duplicate_the_call(stream):
    calls = []
    responses = run_mock_model([200], calls, stream=stream, payloads=[candidate([{
        "functionCall": {"name": "search_grants", "args": {"keyword": "food pantry"}}
    }])])

    assert len(calls) == 1
    assert len(responses) == 1
    assert len(responses[0].get_function_calls()) == 1


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("finish_reason", ["MAX_TOKENS", "SAFETY", "RECITATION", "MALFORMED_FUNCTION_CALL"])
def test_non_stop_and_safety_responses_are_not_retried(stream, finish_reason):
    calls = []
    responses = run_mock_model(
        [200], calls, stream=stream, payloads=[candidate(finish_reason=finish_reason)]
    )

    assert len(calls) == 1
    assert responses[0].finish_reason == finish_reason


@pytest.mark.parametrize("stream", [False, True])
def test_prompt_safety_block_is_not_retried(stream):
    calls = []
    responses = run_mock_model([200], calls, stream=stream, payloads=[{
        "promptFeedback": {"blockReason": "SAFETY", "blockReasonMessage": "Blocked test input"}
    }])

    assert len(calls) == 1
    assert responses[0].error_code == "SAFETY"


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("parts", [[{"text": "  \n\t"}], [{"text": "Internal thought", "thought": True}]])
def test_stop_with_only_whitespace_or_thought_is_treated_as_empty(stream, parts):
    calls = []
    responses = run_mock_model(
        [200], calls, stream=stream,
        payloads=[candidate(parts), candidate([{"text": "Usable answer"}])],
    )

    assert len(calls) == 2
    assert responses[0].content.parts[0].text == "Usable answer"
