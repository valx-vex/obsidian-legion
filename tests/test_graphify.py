"""Tests for Layer 0: Graphify integration."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock
import json

from obsidian_legion.graphify import (
    is_available,
    build_graph,
    query_graph,
)


def test_is_available_when_not_installed() -> None:
    """is_available returns False when graphify is not on PATH."""
    with patch("obsidian_legion.graphify.shutil.which", return_value=None):
        assert is_available() is False


def test_is_available_when_installed() -> None:
    """is_available returns True when graphify is on PATH."""
    with patch("obsidian_legion.graphify.shutil.which", return_value="/usr/local/bin/graphify"):
        assert is_available() is True


def test_build_graph_not_installed(tmp_path: Path) -> None:
    """build_graph returns error when graphify is not installed."""
    with patch("obsidian_legion.graphify.is_available", return_value=False):
        result = build_graph(tmp_path)
        assert result.success is False
        assert "not installed" in (result.error or "").lower()


def test_build_graph_success(tmp_path: Path) -> None:
    """build_graph returns node/edge counts from graph.json."""
    output_dir = tmp_path / "graphify-out"
    output_dir.mkdir()
    graph_file = output_dir / "graph.json"
    graph_file.write_text(json.dumps({
        "nodes": [
            {"id": "A", "community": 0},
            {"id": "B", "community": 0},
            {"id": "C", "community": 1},
        ],
        "edges": [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
        ],
    }))

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Done"
    mock_result.stderr = ""

    with patch("obsidian_legion.graphify.is_available", return_value=True), \
         patch("obsidian_legion.graphify.subprocess.run", return_value=mock_result):
        result = build_graph(tmp_path)
        assert result.success is True
        assert result.node_count == 3
        assert result.edge_count == 2
        assert result.community_count == 2


def test_query_graph_not_installed(tmp_path: Path) -> None:
    """query_graph returns error when graphify is not installed."""
    with patch("obsidian_legion.graphify.is_available", return_value=False):
        answer = query_graph("test question", tmp_path)
        assert "not installed" in answer.lower()
