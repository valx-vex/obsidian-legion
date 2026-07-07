"""R5 semantic-vault graph core (the ``vaultgraph`` package).

Heavy deps (networkx, numpy, scipy, qdrant_client, sentence_transformers) are
imported INSIDE functions only, so importing this package never pulls the
[vaultgraph] extra — the live Legion MCP server keeps working without it.
"""
