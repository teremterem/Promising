from aiohttp import ClientSession
from litellm import acompletion
from pydantic import BaseModel, Field

import promising


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


@promising.function
async def extract_keywords(thought: str, *, litellm_session: ClientSession | None = None) -> list[str]:
    """Extract keywords from a user's thought for semantic similarity search enhancement."""
    model = "openrouter/openai/gpt-5-mini"
    temperature = 0
    reasoning_effort = "low"

    promising.print_trace()

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
        shared_session=litellm_session,
    )

    keyword_response = KeywordResponse.model_validate_json(response.choices[0].message.content)
    return keyword_response.keywords


if __name__ == "__main__":

    @promising.function
    async def main() -> None:
        # TODO [P1] Support arbitrary attributes in PromisingContext to put
        #  things like litellm_session in there. Child contexts should inherit
        #  those attributes from their parents. (Should probably be copied to
        #  children to avoid race conditions.)
        async with ClientSession() as litellm_session:
            try:
                while True:
                    thought = input("Enter a thought:\n")
                    if thought == "exit":
                        break
                    elif not thought.strip():
                        continue
                    keywords = await extract_keywords(thought, litellm_session=litellm_session)
                    print(keywords)
                    print()
            except KeyboardInterrupt:
                pass

    main.run()
