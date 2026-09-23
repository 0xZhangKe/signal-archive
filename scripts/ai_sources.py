"""Load the small, repository-owned AI subscription configuration."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AiSource:
    id: str
    title: str
    prompt_file: Path

    @property
    def feed_path(self) -> str:
        return f"ai/{self.id}.xml"

    def read_prompt(self) -> str:
        text = self.prompt_file.read_text(encoding="utf-8").strip()
        if not text or len(text) > 20_000:
            raise ValueError(f"prompt for {self.id} must contain 1–20000 characters")
        return text


def load_ai_sources(path: Path) -> list[AiSource]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"sources"} or not isinstance(data["sources"], list):
        raise ValueError("AI configuration must contain a sources array")
    sources: list[AiSource] = []
    identifiers: set[str] = set()
    root = path.resolve().parent
    for item in data["sources"]:
        if not isinstance(item, dict) or set(item) != {"id", "title", "promptFile"}:
            raise ValueError("AI sources must contain exactly id, title and promptFile")
        if not all(isinstance(value, str) and value.strip() for value in item.values()):
            raise ValueError("AI source fields must be nonempty strings")
        identifier = item["id"]
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", identifier) or identifier.startswith("folder-"):
            raise ValueError(f"invalid or reserved AI source id: {identifier!r}")
        if identifier in identifiers:
            raise ValueError(f"duplicate AI source id: {identifier!r}")
        identifiers.add(identifier)
        relative = Path(item["promptFile"])
        prompt_file = (root / relative).resolve()
        if relative.is_absolute() or ".." in relative.parts or not prompt_file.is_relative_to(root):
            raise ValueError(f"promptFile must stay inside the configuration directory: {identifier}")
        source = AiSource(identifier, item["title"].strip(), prompt_file)
        source.read_prompt()
        sources.append(source)
    return sources
