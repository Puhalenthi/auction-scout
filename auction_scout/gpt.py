import json
import os
import time
from typing import List

from openai import OpenAI


class GPTNameChecker:
    def __init__(self, model: str = "gpt-5-nano") -> None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set in the environment.")
        self._client = OpenAI(api_key=api_key)
        self._model = os.environ.get("OPENAI_MODEL", model)

    def check_names_batch(self, items: List[dict]) -> List[dict]:
        """Ask GPT whether each person is known in their local community or wider.

        Each item dict must contain: name, city, state, address.
        Returns a list of dicts with keys: is_known (bool), known_for (str),
        scope (str), confidence (float 0-1), reasoning (str).
        """
        if not items:
            return []

        system = (
            "You are an expert researcher. For each person below, determine whether "
            "they are known or notable within their local community or on a wider scale. "
            "Consider politicians, local business owners, athletes, media personalities, "
            "community leaders, activists, criminals with public records, or anyone who "
            "has a public presence.\n\n"
            "Respond ONLY with a JSON array. Each element must be an object with:\n"
            '  "is_known": true/false,\n'
            '  "known_for": brief description of what they are known for (empty string if unknown),\n'
            '  "scope": one of "local", "regional", "national", "international", or "unknown",\n'
            '  "confidence": float between 0 and 1,\n'
            '  "reasoning": one-sentence explanation\n'
            "If unsure, set is_known to false."
        )

        entries = []
        for item in items:
            entries.append(
                f"- Name: {item['name']}, Location: {item.get('address', '')}, "
                f"{item['city']}, {item['state']}"
            )

        user = (
            "Check these people from storage auction notices. Use the location to "
            "help determine if they are known in that community.\n\n"
            + "\n".join(entries)
            + "\n\nReturn a JSON array with one object per person, in the same order."
        )

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
#            temperature=0,
        )
        content = response.choices[0].message.content or ""

        # Try to extract JSON from the response (handle markdown fences)
        json_str = content.strip()
        if json_str.startswith("```"):
            # Remove markdown code fences
            lines = json_str.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            json_str = "\n".join(lines)

        try:
            data = json.loads(json_str)
            if not isinstance(data, list):
                raise ValueError("Non-list response")
        except Exception:
            data = []

        default = {
            "is_known": False,
            "known_for": "",
            "scope": "unknown",
            "confidence": 0.0,
            "reasoning": "GPT parse error",
        }
        results: List[dict] = []
        for idx in range(len(items)):
            if idx < len(data) and isinstance(data[idx], dict):
                entry = data[idx]
                results.append({
                    "is_known": bool(entry.get("is_known", False)),
                    "known_for": str(entry.get("known_for", "")),
                    "scope": str(entry.get("scope", "unknown")),
                    "confidence": float(entry.get("confidence", 0.0)),
                    "reasoning": str(entry.get("reasoning", "")),
                })
            else:
                results.append(dict(default))

        time.sleep(0.2)
        return results
