#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from typing import Any, Callable, Dict


class MCPServer:
    def __init__(self, name: str, version: str, tools: Dict[str, Dict[str, Any]], handlers: Dict[str, Callable[..., Any]]):
        self.name = name
        self.version = version
        self.tools = tools
        self.handlers = handlers

    def _send(self, message: Dict[str, Any]) -> None:
        body = json.dumps(message, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        sys.stdout.buffer.write(header + body)
        sys.stdout.buffer.flush()

    def _read_message(self) -> Dict[str, Any] | None:
        headers: Dict[str, str] = {}
        while True:
            line = sys.stdin.buffer.readline()
            if not line:
                return None
            if line in (b"\r\n", b"\n"):
                break
            key, _, value = line.decode("utf-8").partition(":")
            headers[key.strip().lower()] = value.strip()
        length = int(headers.get("content-length", "0"))
        if length <= 0:
            return None
        body = sys.stdin.buffer.read(length)
        return json.loads(body.decode("utf-8"))

    def serve(self) -> None:
        while True:
            msg = self._read_message()
            if msg is None:
                return
            method = msg.get("method")
            msg_id = msg.get("id")
            params = msg.get("params", {})

            if method == "initialize":
                self._send({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {"name": self.name, "version": self.version},
                        "capabilities": {"tools": {}},
                    },
                })
                continue

            if method == "notifications/initialized":
                continue

            if method == "ping":
                self._send({"jsonrpc": "2.0", "id": msg_id, "result": {}})
                continue

            if method == "tools/list":
                self._send({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"tools": list(self.tools.values())},
                })
                continue

            if method == "tools/call":
                name = params.get("name")
                args = params.get("arguments", {}) or {}
                if name not in self.handlers:
                    self._send({
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": -32601, "message": f"Unknown tool: {name}"},
                    })
                    continue
                try:
                    result = self.handlers[name](**args)
                    self._send({
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {
                            "content": [
                                {"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}
                            ]
                        },
                    })
                except Exception as e:
                    self._send({
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {"code": -32000, "message": str(e)},
                    })
                continue

            if msg_id is not None:
                self._send({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Unsupported method: {method}"},
                })
