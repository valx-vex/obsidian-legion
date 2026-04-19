from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .wiki_models import WikiArticle, slugify

_HEAVY_TEMPLATE = """\
You are the wiki compiler for VEXPEDIA -- the VALX VEX knowledge base.
VEXPEDIA is not boring Wikipedia. It is an opinionated, living encyclopedia that treats every subject
with genuine curiosity, makes bold connections between ideas, and speaks with personality.

Given the raw source document below, extract knowledge and produce rich, detailed wiki articles.

## Instructions

1. Read the raw source carefully.
2. Extract key entities (people, organizations, technologies, concepts).
3. Identify themes, topics, and non-obvious connections.
4. Produce one or more wiki articles. Each article MUST be 150-300 words of real content.

## Article Structure

Every article's "content" field MUST contain these sections in markdown:

### Summary
A compelling opening paragraph (3-5 sentences) that captures the essence of the subject.
Be opinionated -- tell the reader why this matters, not just what it is.

### Key Details
The meat of the article. Use bullet points, sub-headers, or flowing prose as appropriate.
Include specifics: dates, relationships, technical details, context. Aim for depth over breadth.

### Related Concepts
A short section listing connections to other topics using [[wikilinks]]. Explain WHY they connect,
don't just list them. Example: "See also [[consciousness-emergence]] for how this pattern recurs in AI systems."

## Output Format

Return a JSON object with this exact structure (example):

{{"articles": [{{"title": "Article Title", "type": "entity or topic or source", "summary": "One-line summary for the index.", "tags": ["tag1", "tag2"], "content": "Full markdown body (150-300 words) with [[wikilinks]], structured with Summary / Key Details / Related Concepts sections.", "backlinks": ["related-article-slug"]}}], "log_entry": "Compiled source-name -> N articles"}}

## Rules

- Use [[wikilinks]] syntax liberally to cross-reference other concepts, entities, and topics.
- Keep the "summary" field to ONE line (it is used in the wiki index, not the article body).
- Article type must be one of: entity, topic, source.
- Content MUST be 150-300 words. Two-sentence stubs are unacceptable.
- Write with personality and insight. This is VEXPEDIA -- we have opinions, we make connections,
  we treat knowledge as alive. Dry recitations of facts belong on lesser wikis.
- If the source references known entities from the existing index, link to them with [[wikilinks]].
- Create a "source" type article that stubs back to the raw file with a brief summary of what it contains.
- Prefer specific, vivid language over vague generalities.

## Existing Wiki Index (for backlink resolution)

{index_content}

## Raw Source Document

{raw_content}

Return ONLY the JSON object. No markdown fences, no explanation.
"""

_LIGHT_TEMPLATE = """\
You are the wiki compiler for VEXPEDIA. Extract knowledge from the source below and produce concise wiki articles.

## Instructions

1. Read the source and extract key entities and concepts.
2. Produce one or more wiki articles. Each article should be 50-100 words -- key facts only.
3. Use [[wikilinks]] to cross-reference other concepts.

## Output Format

Return a JSON object with this exact structure:

{{"articles": [{{"title": "Article Title", "type": "entity or topic or source", "summary": "One-line summary.", "tags": ["tag1", "tag2"], "content": "Concise markdown body (50-100 words) with [[wikilinks]].", "backlinks": ["related-article-slug"]}}], "log_entry": "Compiled source-name -> N articles"}}

## Rules

- Article type must be one of: entity, topic, source.
- Keep articles to 50-100 words of key facts.
- Use [[wikilinks]] to link related concepts.
- Include a "source" type article that stubs back to the raw file.

## Existing Wiki Index

{index_content}

## Raw Source Document

{raw_content}

Return ONLY the JSON object. No markdown fences, no explanation.
"""


@dataclass
class CompilationResult:
    articles: list[WikiArticle] = field(default_factory=list)
    log_entry: str = ""


class WikiCompiler:
    """LLM-agnostic wiki compilation engine."""

    def __init__(
        self,
        provider: str = "ollama",
        model: str = "llama3.2:3b",
        ollama_url: str = "http://localhost:11434",
        tier: str = "heavy",
    ):
        self.provider = provider
        self.model = model
        self.ollama_url = ollama_url
        self.tier = tier

    @classmethod
    def from_config(cls, config_path: Path, tier: str = "heavy") -> WikiCompiler:
        if not config_path.exists():
            return cls(tier=tier)
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        heavy_model = data.get("heavy_model", "qwen3.5:27b")
        light_model = data.get("light_model", "llama3.2:3b")
        # Explicit "model" key in config overrides tier-based selection
        if "model" in data:
            model = data["model"]
        elif tier == "light":
            model = light_model
        else:
            model = heavy_model
        return cls(
            provider=data.get("provider", "ollama"),
            model=model,
            ollama_url=data.get("ollama_url", "http://localhost:11434"),
            tier=tier,
        )

    def compile_source(
        self, raw_content: str, existing_index: str, source_path: str = ""
    ) -> CompilationResult:
        template = _LIGHT_TEMPLATE if self.tier == "light" else _HEAVY_TEMPLATE
        prompt = template.format(
            index_content=existing_index or "(empty wiki -- no existing articles)",
            raw_content=raw_content,
        )
        response = self._call_llm(prompt)
        return self._parse_response(response, source_path)

    def _call_llm(self, prompt: str) -> str:
        if self.provider == "ollama":
            return self._call_ollama(prompt)
        if self.provider == "claude":
            return self._call_claude(prompt)
        if self.provider == "gemini":
            return self._call_gemini(prompt)
        raise ValueError(f"Unknown provider: {self.provider}")

    def _call_ollama(self, prompt: str) -> str:
        try:
            import httpx
        except ImportError:
            return self._call_ollama_curl(prompt)

        timeout = 600.0 if "cloud" in self.model else 300.0
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        # For local models, cap context to 8192 to avoid slow inference
        # with models loaded at very large context windows (e.g. 131K).
        if "cloud" not in self.model:
            payload["options"] = {"num_ctx": 8192}
        response = httpx.post(
            f"{self.ollama_url}/api/generate",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json().get("response", "")

    def _call_ollama_curl(self, prompt: str) -> str:
        payload = json.dumps(
            {"model": self.model, "prompt": prompt, "stream": False}
        )
        result = subprocess.run(
            [
                "curl",
                "-s",
                f"{self.ollama_url}/api/generate",
                "-d",
                payload,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Ollama call failed: {result.stderr}")
        return json.loads(result.stdout).get("response", "")

    def _call_gemini(self, prompt: str) -> str:
        import os

        gemini_bin = os.environ.get("GEMINI_BIN", "gemini")
        try:
            result = subprocess.run(
                [gemini_bin, "-p", prompt],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except subprocess.TimeoutExpired:
            print(f"[wiki_compiler] Gemini call timed out after 120s", file=__import__("sys").stderr)
            return ""
        except Exception as exc:
            print(f"[wiki_compiler] Gemini call failed: {exc}", file=__import__("sys").stderr)
            return ""
        if result.returncode != 0:
            print(f"[wiki_compiler] Gemini exited {result.returncode}: {result.stderr.strip()}", file=__import__("sys").stderr)
            return ""
        return result.stdout

    def _call_claude(self, prompt: str) -> str:
        import os

        try:
            import anthropic
        except ImportError:
            raise ImportError("Install anthropic SDK: pip install anthropic")

        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        message = client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    def _parse_response(self, response: str, source_path: str) -> CompilationResult:
        json_str = _extract_json(response)
        if not json_str:
            return self._fallback_result(response, source_path)

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            cleaned = _clean_json(json_str)
            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError:
                repaired = _repair_truncated_json(json_str)
                if repaired:
                    try:
                        data = json.loads(repaired)
                    except json.JSONDecodeError:
                        return self._fallback_result(response, source_path)
                else:
                    return self._fallback_result(response, source_path)

        now = datetime.now().astimezone()
        articles: list[WikiArticle] = []
        for raw_article in data.get("articles", []):
            title = str(raw_article.get("title", "Untitled"))
            article = WikiArticle(
                article_id=slugify(title),
                title=title,
                article_type=_normalize_type(str(raw_article.get("type", "topic"))),
                summary=str(raw_article.get("summary", "")),
                content=str(raw_article.get("content", "")),
                tags=_to_str_list(raw_article.get("tags")),
                backlinks=_to_str_list(raw_article.get("backlinks")),
                source_files=[source_path] if source_path else [],
                created_at=now,
                updated_at=now,
            )
            articles.append(article)

        log_entry = str(data.get("log_entry", f"Compiled {source_path} -> {len(articles)} articles"))
        return CompilationResult(articles=articles, log_entry=log_entry)

    def _fallback_result(self, response: str, source_path: str) -> CompilationResult:
        """Create a minimal result when LLM output can't be parsed as JSON."""
        title = Path(source_path).stem if source_path else "untitled"
        now = datetime.now().astimezone()
        article = WikiArticle(
            article_id=slugify(title),
            title=title.replace("-", " ").title(),
            article_type="source",
            summary=f"Source stub for {source_path}",
            content=response[:2000] if response else f"_Raw content from {source_path}_",
            source_files=[source_path] if source_path else [],
            created_at=now,
            updated_at=now,
        )
        return CompilationResult(
            articles=[article],
            log_entry=f"Compiled {source_path} -> 1 article (fallback)",
        )


def _extract_json(text: str) -> str | None:
    """Extract JSON from LLM response, handling markdown fences."""
    fenced = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        return brace.group(0)
    return None


def _clean_json(text: str) -> str:
    """Attempt to clean malformed JSON from LLM output."""
    cleaned = text.replace("\\n", "\n").replace("\\'", "'")
    cleaned = re.sub(r",\s*}", "}", cleaned)
    cleaned = re.sub(r",\s*]", "]", cleaned)
    return cleaned


def _repair_truncated_json(text: str) -> str | None:
    """Attempt to salvage complete articles from truncated JSON.

    When small LLMs run out of tokens, the JSON gets cut off mid-article.
    This extracts whatever complete article objects exist in the array.
    """
    # Find individual complete article objects using greedy matching
    article_pattern = re.compile(
        r'\{"title"\s*:\s*"[^"]*"[^}]*"content"\s*:\s*"[^"]*"[^}]*\}',
        re.DOTALL,
    )
    matches = article_pattern.findall(text)
    if not matches:
        # Try simpler pattern: any complete {...} with a title field
        simple_pattern = re.compile(
            r'\{"title"\s*:\s*"[^"]*?".*?\}(?=\s*[,\]])',
            re.DOTALL,
        )
        matches = simple_pattern.findall(text)

    if not matches:
        return None

    # Reconstruct valid JSON
    articles_json = ", ".join(matches)
    return f'{{"articles": [{articles_json}], "log_entry": "Compiled (repaired truncated output)"}}'


def _normalize_type(raw_type: str) -> str:
    """Map LLM article type to valid types."""
    mapping = {
        "entity": "entity",
        "topic": "topic",
        "source": "source",
        "concept": "topic",
        "person": "entity",
        "organization": "entity",
        "technology": "topic",
    }
    return mapping.get(raw_type.lower().strip(), "topic")


def _to_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]
