"""Model transport settings for the local ADK demo."""

import logging

from google.adk.models.google_llm import Gemini
from google.adk.models.llm_response import LlmResponse
from google.genai import types


logger = logging.getLogger(__name__)


def _empty_terminal_response(response: LlmResponse) -> bool:
    """Recognize ADK's empty STOP case without retrying refusals or tool calls.

    Match the meaningful-content categories in ADK's empty-response policy,
    keeping this small check local rather than importing a private ADK helper.
    """
    if (
        response.partial
        or response.interrupted
        or response.error_code is not None
        or response.finish_reason != types.FinishReason.STOP
    ):
        return False
    parts = response.content.parts if response.content else []
    for part in parts or []:
        if any(
            getattr(part, name, None) is not None
            for name in (
                "function_call", "function_response", "executable_code",
                "code_execution_result", "inline_data", "file_data",
            )
        ):
            return False
        if not part.thought and part.text and part.text.strip():
            return False
    return True


class BufferedGemini(Gemini):
    """Buffer model turns and retry one successful-but-empty STOP response.

    The SDK can raise an error from a successful HTTP SSE response after its
    retry scope has ended. Using generateContent avoids that path. ADK still
    emits agent and tool events to the browser; model text arrives at the end
    of each model turn. An empty STOP gets one retry of the same model request,
    before any content is exposed to ADK. Tools and the workflow are not
    replayed. If the retry is also empty, return it unchanged so ADK can surface
    the failure.
    """

    async def generate_content_async(self, llm_request, stream=False):
        for attempt in range(2):
            responses = [
                response async for response in super().generate_content_async(
                    llm_request, stream=False
                )
            ]
            empty = len(responses) == 1 and _empty_terminal_response(responses[0])
            if empty and attempt == 0:
                logger.warning("Model returned an empty STOP response; retrying the model request once.")
                continue
            if empty:
                logger.warning("Model retry also returned an empty STOP response; returning it to ADK.")
            for response in responses:
                yield response
            return
