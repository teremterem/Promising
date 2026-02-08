from litellm import acompletion
from pydantic import BaseModel, Field


class KeywordResponse(BaseModel):
    """Keywords extracted from a user's thought for enhancing semantic similarity search."""

    keywords: list[str] = Field(
        description=(
            "A list of keywords and short key phrases extracted from the thought. "
            "Include the most important terms that capture the core meaning, "
            "as well as synonyms and closely related terms that someone might "
            "use when searching for this thought. Do not include stop words "
            "or overly generic terms. If there are no useful keywords, return an empty list."
        ),
    )


async def extract_keywords(thought: str) -> list[str]:
    """Extract keywords from a user's thought for semantic similarity search enhancement."""
    model = "openrouter/openai/gpt-5-mini"
    temperature = 0
    reasoning_effort = "low"

    response = await acompletion(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a keyword extraction assistant. Extract the most relevant keywords "
                    "and short key phrases from the given thought. Include synonyms and closely "
                    "related terms that would help with semantic similarity search. "
                    "Return keywords in the same language as the thought. "
                    "If there are no useful keywords, return an empty list"
                ),
            },
            {
                "role": "user",
                "content": thought,
            },
        ],
        temperature=temperature,
        reasoning_effort=reasoning_effort,
        response_format=KeywordResponse,
    )

    keyword_response = KeywordResponse.model_validate_json(response.choices[0].message.content)
    return keyword_response.keywords
