"""
tools/cockpit_smoke.py
========================

卷二十五 · cockpit 聚合 endpoint + Cache-Control · smoke 测试

跑：
  py tools/cockpit_smoke.py

覆盖：
  1. GET /dashboard/cockpit · 401 (no auth) / 200 (auth)
  2. 返回 domains 必须含 8 个维度 (chat 不算 · radar/trends/reports + 5 stub)
  3. 每个维度 schema：id / label / icon / items / total / stub / empty_hint
  4. radar / trends / reports 三个实现维度 stub=False
  5. content / service / design / dev / docs 五个 stub=True
  6. head 参数生效：head=1 → 每个 items 长度 <= 1
  7. /static/chat.js 响应必须含 Cache-Control: no-cache
  8. /dashboard/cockpit 404 forwarding：不存在的 domain 仍走原 dashboard endpoint
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["OPUS_API_TOKEN"] = "smoke-test-token-do-not-leak"


class CockpitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient  # noqa
        except ImportError:
            raise unittest.SkipTest("fastapi.testclient 不可用")

        from daemon_api import build_app

        cls.app = build_app()
        from fastapi.testclient import TestClient
        cls.client = TestClient(cls.app)
        cls.token = os.environ["OPUS_API_TOKEN"]
        cls.auth = {"Authorization": f"Bearer {cls.token}"}

    def test_no_auth_401(self):
        r = self.client.get("/dashboard/cockpit")
        self.assertEqual(r.status_code, 401)

    def test_happy_path_default_head(self):
        r = self.client.get("/dashboard/cockpit", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertIn("generated_at", data)
        self.assertEqual(data["head"], 3)
        self.assertIn("domains", data)
        # 卷二十九: 12 维 = 卷二十八 10 维 + feasibility + plugins
        self.assertEqual(len(data["domains"]), 12,
                         f"应该有 12 个维度: {[d['id'] for d in data['domains']]}")

    def test_domain_schema_complete(self):
        r = self.client.get("/dashboard/cockpit", headers=self.auth)
        data = r.json()
        required_keys = {"id", "label", "icon", "items", "total", "stub", "empty_hint"}
        for d in data["domains"]:
            keys = set(d.keys())
            missing = required_keys - keys
            self.assertFalse(missing, f"维度 {d.get('id')} 缺字段: {missing}")
            self.assertIsInstance(d["items"], list)
            self.assertIsInstance(d["total"], int)
            self.assertIsInstance(d["stub"], bool)

    def test_live_domains_not_stub(self):
        r = self.client.get("/dashboard/cockpit", headers=self.auth)
        data = r.json()
        live_ids = {d["id"] for d in data["domains"] if not d["stub"]}
        # 卷二十九: 实现维度 + feasibility + plugins
        self.assertEqual(
            live_ids,
            {"radar", "trends", "reports", "opportunities", "cognition",
             "content", "design", "dev", "docs",
             "feasibility", "plugins"},
            "卷二十九·实现维度应该是上面这些",
        )

    def test_stub_domains_marked(self):
        r = self.client.get("/dashboard/cockpit", headers=self.auth)
        data = r.json()
        stub_ids = {d["id"] for d in data["domains"] if d["stub"]}
        # 卷二十六: 只有 service 还是 stub (BRO: 等先有产品再做)
        self.assertEqual(stub_ids, {"service"})
        for d in data["domains"]:
            if d["stub"]:
                self.assertEqual(d["items"], [])
                self.assertEqual(d["total"], 0)

    def test_head_parameter(self):
        # head=1
        r = self.client.get("/dashboard/cockpit?head=1", headers=self.auth)
        data = r.json()
        self.assertEqual(data["head"], 1)
        for d in data["domains"]:
            self.assertLessEqual(len(d["items"]), 1)

        # head=10 上限
        r = self.client.get("/dashboard/cockpit?head=100", headers=self.auth)
        data = r.json()
        self.assertEqual(data["head"], 10, "上限应该 cap 在 10")

        # head=0 应该被 clamp 到 1
        r = self.client.get("/dashboard/cockpit?head=0", headers=self.auth)
        data = r.json()
        self.assertEqual(data["head"], 1)

    def test_cache_control_on_static(self):
        # 单独测：/static/chat.js 必须有 Cache-Control: no-cache
        # 这是为了让 BRO 改 chat.js 后浏览器自动看到新版
        r = self.client.get("/static/chat.js")
        self.assertEqual(r.status_code, 200)
        cc = r.headers.get("cache-control", "").lower()
        self.assertIn("no-cache", cc, f"chat.js 没有 no-cache header: {cc}")

        r = self.client.get("/static/chat.css")
        self.assertEqual(r.status_code, 200)
        cc = r.headers.get("cache-control", "").lower()
        self.assertIn("no-cache", cc, f"chat.css 没有 no-cache header: {cc}")

    def test_cockpit_path_not_confused_with_domain(self):
        # 关键：'cockpit' 不能被原 /dashboard/{domain} 当成 stub domain
        # 因为 FastAPI 会按声明顺序匹配 · /dashboard/cockpit 必须在 /dashboard/{domain} 之前
        r = self.client.get("/dashboard/cockpit", headers=self.auth)
        data = r.json()
        # cockpit 返回的应该是聚合数据 (有 generated_at / head / domains)
        # 不是 stub 形式 ({domain: 'cockpit', status: 'stub'})
        self.assertIn("generated_at", data)
        self.assertNotIn("status", data)

    def test_invalid_domain_still_404(self):
        # 验证未知 domain 仍返回 404（原 dashboard endpoint 走兜底）
        r = self.client.get("/dashboard/this-does-not-exist", headers=self.auth)
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
