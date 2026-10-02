"""Check that the AI (Groq) key in .env works. Run from the backend/ folder:
    python -m scripts.check_llm
Prints the model's short reply. The key itself is never printed.
"""
import sys

from app import config, llm


def main() -> int:
    if not llm.is_configured():
        print("LLM_API_KEY is missing in .env")
        return 1
    print(f"service: {config.LLM_BASE_URL}")
    print(f"model:   {config.LLM_MODEL}")
    try:
        reply = llm.chat([{"role": "user", "content": "Reply with exactly: AI is working"}], max_tokens=300)
    except llm.LLMError as error:
        print(f"FAILED: {error}")
        return 1
    print(f"reply:   {reply}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
