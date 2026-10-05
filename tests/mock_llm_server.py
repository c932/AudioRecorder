"""最小 OpenAI 兼容 + MiniCPM-o 假服务 — 离线验证 Web 设置页「测试连接」。

用法：python tests/mock_llm_server.py [port]（默认 9099）

端点：
- GET  /v1/models                     → 两个假模型（openai SDK models.list）
- POST /v1/chat/completions           → 一条固定回复
- POST /api/auth/login                → {"token": ...}（Omni JWT 登录）
- GET  /api/omni/minicpm-o45/status   → {"state": "ready"}（Omni 状态）
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[mock] {self.command} {self.path}", flush=True)

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/models":
            self._json({"object": "list", "data": [
                {"id": "mock-model", "object": "model", "created": 0, "owned_by": "mock"},
                {"id": "mock-mini", "object": "model", "created": 0, "owned_by": "mock"},
            ]})
        elif self.path == "/api/omni/minicpm-o45/status":
            self._json({"state": "ready", "status": "ready"})
        else:
            self._json({"error": {"message": f"not found: {self.path}"}}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        if self.path == "/v1/chat/completions":
            self._json({
                "id": "chatcmpl-mock", "object": "chat.completion", "created": 0,
                "model": "mock-model",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": "hi"},
                    "finish_reason": "stop",
                }],
            })
        elif self.path == "/api/auth/login":
            self._json({"token": "mock-jwt-token", "expires_in": 86400})
        else:
            self._json({"error": {"message": f"not found: {self.path}"}}, 404)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9099
    print(f"[mock] listening on http://127.0.0.1:{port}", flush=True)
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
