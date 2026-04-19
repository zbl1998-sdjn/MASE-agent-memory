from __future__ import annotations

import json
import shutil
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from mase import MASESystem
from model_interface import load_config, resolve_config_path

BASE_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BASE_DIR / "memory_runs" / "cloud-backend-validation"
TEMP_CONFIG_PATH = WORKSPACE_DIR / "config.cloud.mock.json"


class MockCloudHandler(BaseHTTPRequestHandler):
    request_log: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        model = payload.get("model", "")
        messages = payload.get("messages") or []
        tools = payload.get("tools")
        text = "\n".join(str(message.get("content", "")) for message in messages)
        system_text = next((str(message.get("content", "")) for message in messages if message.get("role") == "system"), "")

        self.request_log.append(
            {
                "path": self.path,
                "model": model,
                "has_tools": bool(tools),
                "system_preview": system_text[:80],
                "user_preview": text[:120],
            }
        )

        response_body = self._build_response(model, system_text, text, tools)
        body = json.dumps(response_body, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _build_response(
        self,
        model: str,
        system_text: str,
        text: str,
        tools: list[dict] | None,
    ) -> dict:
        content = "好的。"

        if "路由智能体" in system_text:
            if "服务器端口" in text or "刚才记住" in text:
                content = '{"action":"search_memory","keywords":["服务器端口"]}'
            else:
                content = '{"action":"direct_answer","keywords":[]}'
        elif "事实记录员" in system_text:
            content = "用户要求记住：服务器端口是9909。"
        elif tools:
            content = "已准备调用工具。"
        elif "事实备忘录" in text and "code_generation" in text:
            content = "```python\nconfig = {\n    'server_port': 9909\n}\n```"
        elif "事实备忘录" in text:
            content = "根据记录，服务器端口是9909。"
        elif "math_compute" in system_text or "数学计算" in system_text or "等于多少" in text:
            content = "结果是 168。"
        elif "记住" in text:
            content = "好的，我已记录。后续你可以随时问我相关的问题。"

        return {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "created": 1710000000,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content,
                    },
                    "finish_reason": "stop",
                }
            ],
        }


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def write_config(config: dict) -> None:
    TEMP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    TEMP_CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    memory_dir = (WORKSPACE_DIR / "memory").resolve()
    if memory_dir.exists():
        shutil.rmtree(memory_dir)
    MockCloudHandler.request_log = []

    port = get_free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), MockCloudHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        config = load_config(resolve_config_path(BASE_DIR / "config.cloud.example.json"))
        for agent_type, model_name in (
            ("router", "deepseek-chat"),
            ("notetaker", "glm-4-flash"),
            ("executor", "MiniMax-Text-01"),
        ):
            config["models"][agent_type]["base_url"] = f"http://127.0.0.1:{port}/v1"
            config["models"][agent_type]["api_key"] = f"mock-{agent_type}-key"
            config["models"][agent_type].pop("api_key_env", None)
            config["models"][agent_type]["model_name"] = model_name

        config["memory"]["json_dir"] = str(memory_dir)
        config["memory"]["index_db"] = str((memory_dir / "index.db").resolve())
        write_config(config)

        system = MASESystem(TEMP_CONFIG_PATH)
        trace1 = system.run_with_trace("请记住：服务器端口是9909。", log=False)
        trace2 = system.run_with_trace("根据我们刚才记住的服务器端口，写一个Python配置字典。", log=False)
        route = system.call_router("服务器端口是多少？")

        report = {
            "config_path": str(TEMP_CONFIG_PATH),
            "record_path": trace1.record_path,
            "route_after_cloud_switch": route,
            "trace1_answer": trace1.answer,
            "trace2_task_type": trace2.plan.task_type,
            "trace2_use_memory": trace2.plan.use_memory,
            "trace2_answer": trace2.answer,
            "request_models": [item["model"] for item in MockCloudHandler.request_log],
            "record_path_in_mock_memory": trace1.record_path.startswith(str(memory_dir)),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
