"""Optional LLM helper. Off unless an API key is set, so everything else runs
offline. The provider is picked from whichever key is present (Gemini, Groq, or
any OpenAI-compatible endpoint). Returns None on any problem, so callers fall
back to their deterministic answer.
"""
import json
import os
import urllib.request


def available():
    return bool(os.environ.get("GEMINI_API_KEY")
                or os.environ.get("GROQ_API_KEY")
                or os.environ.get("OPENAI_API_KEY"))


def ask_llm(prompt, max_tokens=300):
    model = os.environ.get("LLM_MODEL")
    try:
        if os.environ.get("GEMINI_API_KEY"):
            return _gemini(prompt, model or "gemini-2.0-flash", max_tokens)
        if os.environ.get("GROQ_API_KEY"):
            return _chat("https://api.groq.com/openai/v1/chat/completions",
                         os.environ["GROQ_API_KEY"], model or "llama-3.3-70b-versatile", prompt, max_tokens)
        if os.environ.get("OPENAI_API_KEY"):
            return _chat("https://api.openai.com/v1/chat/completions",
                         os.environ["OPENAI_API_KEY"], model or "gpt-4o-mini", prompt, max_tokens)
    except Exception:
        return None
    return None


def _post(url, headers, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={**headers, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _gemini(prompt, model, max_tokens):
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
           f"?key={os.environ['GEMINI_API_KEY']}")
    j = _post(url, {}, {"contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"maxOutputTokens": max_tokens}})
    return j["candidates"][0]["content"]["parts"][0]["text"].strip()


def _chat(url, key, model, prompt, max_tokens):
    j = _post(url, {"Authorization": f"Bearer {key}"},
              {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]})
    return j["choices"][0]["message"]["content"].strip()
