import json
import os
import re

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
_client = None


def client():
    global _client
    key = os.getenv("OPENAI_API_KEY")
    if _client is None and key:
        _client = OpenAI(api_key=key, base_url=os.getenv("OPENAI_BASE_URL") or None)
    return _client

def available() -> bool:
    return client() is not None


def ask(system: str, content, max_tokens: int = 1500, history=None):
    c = client()
    if not c:
        return None
    messages = [{"role": "system", "content": system}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": content})
    try:
        r = c.chat.completions.create(model=MODEL, messages=messages, max_tokens=max_tokens)
        return r.choices[0].message.content or ""
    except Exception as e:
        print("OpenAI LLM error:", e)
        return None


def ask_json(system: str, content, max_tokens: int = 2000):
    text = ask(system + "\nRespond with ONLY valid JSON, no markdown fences.", content, max_tokens)
    if not text:
        return None
    text = re.sub(r"```(?:json)?", "", text).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None