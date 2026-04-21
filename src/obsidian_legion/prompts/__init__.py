"""VEXPEDIA prompt pack loader.

Load specialized compilation prompts for different article types.
Prompt files use ``{{placeholder}}`` markers (double-brace) so that the
abundant JSON examples inside each template do not conflict with Python's
``str.format()`` machinery.  Call :func:`render_prompt` to substitute
``index_content`` and ``raw_content`` into the loaded template.
"""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent
_DEFAULT_TYPE = "topic"


def available_prompts() -> list[str]:
    """Return sorted list of available prompt type names."""
    return sorted(p.stem for p in _PROMPTS_DIR.glob("*.txt"))


def load_prompt(article_type: str) -> str:
    """Load the raw prompt template for *article_type*.

    Falls back to the ``topic`` prompt when the requested type is not
    found.  Returns the template string with ``{{index_content}}`` and
    ``{{raw_content}}`` markers still in place.
    """
    path = _PROMPTS_DIR / f"{article_type}.txt"
    if not path.exists():
        path = _PROMPTS_DIR / f"{_DEFAULT_TYPE}.txt"
    if not path.exists():
        raise FileNotFoundError(
            f"No prompt file for type '{article_type}' and no fallback "
            f"'{_DEFAULT_TYPE}.txt' found in {_PROMPTS_DIR}"
        )
    return path.read_text(encoding="utf-8")


def render_prompt(
    article_type: str,
    *,
    index_content: str = "(empty wiki -- no existing articles)",
    raw_content: str = "",
) -> str:
    """Load and render a prompt, substituting placeholders.

    Parameters
    ----------
    article_type:
        One of the available prompt types (``entity``, ``concept``,
        ``event``, ``source``, or any custom ``.txt`` file stem).
    index_content:
        Existing wiki index used for backlink resolution.
    raw_content:
        The raw source document to compile.
    """
    template = load_prompt(article_type)
    return (
        template
        .replace("{{index_content}}", index_content)
        .replace("{{raw_content}}", raw_content)
    )
