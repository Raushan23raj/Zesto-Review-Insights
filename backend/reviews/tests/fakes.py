"""A fake LLM so the tests run without a key or network."""
import re

from reviews import labelling

TAXONOMY = {"themes": [
    {"name": "Delivery", "description": "Getting the order to the door",
     "sub_themes": [{"name": "Delivery Time", "description": ""}, {"name": "Rider Behaviour", "description": ""}]},
    {"name": "Food Quality", "description": "The food itself",
     "sub_themes": [{"name": "Taste", "description": ""}, {"name": "Temperature", "description": ""}]},
]}

# keyword -> topic the fake "model" returns
RULES = [
    ("late", {"theme": "Delivery", "sub_theme": "Delivery Time", "sentiment": "negative"}),
    ("rude", {"theme": "delivery", "sub_theme": "Rider behaviour", "sentiment": "negative"}),  # odd casing on purpose
    ("cold", {"theme": "Food Quality", "sub_theme": "Temperature", "sentiment": "negative"}),
    ("tasty", {"theme": "Food Quality", "sub_theme": "Taste", "sentiment": "positive"}),
    ("wallet", {"theme": "Loyalty Wallet", "sub_theme": "Wallet Balance", "sentiment": "negative", "new": True}),
]


class FakeLLM:
    def __init__(self, drop_ids=()):
        self.calls = []
        self.drop_ids = set(drop_ids)  # pretend the model forgets these reviews

    def __call__(self, system, prompt, **kwargs):
        self.calls.append(prompt)
        if system == labelling.DISCOVERY_SYSTEM:
            return TAXONOMY
        results = []
        for line in prompt.split("Reviews (id | rating | text):", 1)[1].strip().splitlines():
            rid, _rating, text = [p.strip() for p in line.split("|", 2)]
            if rid in self.drop_ids:
                continue
            topics = [t for kw, t in RULES if re.search(kw, text, re.I)]
            results.append({"id": rid, "topics": topics or [{"theme": "NONE", "sub_theme": "NONE", "sentiment": "neutral"}]})
        return {"results": results}
