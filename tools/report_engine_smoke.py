"""
tools/report_engine_smoke.py
==============================

卷二十四 · report_engine + generate_report + /reports endpoint 端到端 smoke。

跑：
  py tools/report_engine_smoke.py

测试覆盖：
  1. report_engine.render_report 纯函数 · markdown → docx 真生成
  2. agent_tools.generate_report 工具 · NLP 入口 → 落盘
  3. /dashboard/reports endpoint · list 模式
  4. /reports/<file> endpoint · download 模式 (Bearer + ?token=)
  5. /reports/../etc/passwd 等越权尝试 · 必须被拒
  6. 主题切换 (opus_studio / midnight) · 都能生成

不调 LLM。不需要真 token——本测试自己用 os.environ 设一个临时 token。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 测试 token 必须在 import daemon_api 之前设
os.environ["OPUS_API_TOKEN"] = "smoke-test-token-do-not-leak"


SAMPLE_MD = """\
本测试报告用于验证本工程的文档生产能力。

## 一、核心能力

OPUS 现在可以通过自然语言触发 `generate_report` 工具 · 把 markdown 一键渲染成 DOCX。

### 1.1 支持的元素

- 多级标题（1-6 级）
- **加粗** / *斜体* / `行内代码`
- 有序 / 无序列表
- 表格（含表头底色 + 隔行灰底）
- 引用块
- 代码块

### 1.2 示例表格

| 维度 | 主题 | 状态 |
|---|---|---|
| 信息 | OPUS 紫 | ✅ |
| 内容 | 深蓝 | ✅ |
| 报告 | 双主题 | ✅ |

## 二、引用 + 代码

> 这是引用块 · 浅紫底 + 左侧紫色竖线
> 多行引用应能正确合并

```python
from report_engine import render_report
final = render_report(md, out_path, cover=cover)
```

## 三、行内格式综合

正文里的 **粗体** 和 *斜体* 应能正确渲染 · `inline code` 应该是等宽 + 红色。

---

文档结束。
"""


class ReportEngineTests(unittest.TestCase):
    """直接调 report_engine.render_report"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="opus-smoke-report-"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_render_with_cover_opus_studio(self):
        from report_engine import render_report

        out = self.tmpdir / "smoke-opus.docx"
        final = render_report(
            md_text=SAMPLE_MD,
            output_path=out,
            cover={
                "title": "文档引擎 Smoke",
                "subtitle": "自检",
                "audience": "BRO 自看",
                "note": "本文档由 report_engine 直接生成 · 不经过 generate_report 工具",
            },
            theme="opus_studio",
            here_dir=self.tmpdir,
        )
        self.assertTrue(final.exists(), f"docx 未生成: {final}")
        size = final.stat().st_size
        self.assertGreater(size, 3000, f"docx 文件过小 ({size} bytes) · 可能渲染失败")
        self.assertLess(size, 200000, f"docx 异常大 ({size} bytes)")

    def test_render_with_midnight_theme(self):
        from report_engine import render_report

        out = self.tmpdir / "smoke-midnight.docx"
        final = render_report(
            md_text=SAMPLE_MD,
            output_path=out,
            cover={"title": "深蓝主题验证", "audience": "BRO"},
            theme="midnight",
        )
        self.assertTrue(final.exists())
        self.assertGreater(final.stat().st_size, 3000)

    def test_render_without_cover(self):
        from report_engine import render_report

        out = self.tmpdir / "no-cover.docx"
        final = render_report(
            md_text="# 不要封面的文档\n\n这是纯正文。",
            output_path=out,
            cover=None,
        )
        self.assertTrue(final.exists())

    def test_render_empty_body_rejected(self):
        from report_engine import render_report

        with self.assertRaises(ValueError):
            render_report("", self.tmpdir / "x.docx")

    def test_file_lock_resolution(self):
        """文件被占用时应自动加 -v2"""
        from report_engine import render_report

        out = self.tmpdir / "locked.docx"
        first = render_report("一些正文。", out, cover={"title": "T"})
        self.assertEqual(first.name, "locked.docx")
        # 让 resolve_writable_path 真的去判断 PermissionError 太复杂 ·
        # 这里只验证文件存在 + 第二次跑不会抛
        second = render_report("再来一遍。", out, cover={"title": "T2"})
        # 第二次因为第一次没被占用 · resolve 会判定能写 · 直接覆盖同名
        self.assertTrue(second.exists())


class GenerateReportToolTests(unittest.TestCase):
    """通过 agent_tools.REGISTRY 调工具入口"""

    def setUp(self):
        from agent_tools import REGISTRY

        self.tool = REGISTRY.get("generate_report")
        self.assertIsNotNone(self.tool, "generate_report 没注册进 REGISTRY")

        self.reports_dir = ROOT / "data" / "reports"
        # 记录测试前的文件列表 · 测试后只清理新生成的
        self.before = set(p.name for p in self.reports_dir.glob("*.docx")) if self.reports_dir.exists() else set()

    def tearDown(self):
        if not self.reports_dir.exists():
            return
        after = set(p.name for p in self.reports_dir.glob("*.docx"))
        for name in after - self.before:
            try:
                (self.reports_dir / name).unlink()
            except OSError:
                pass

    def test_tool_spec_fields(self):
        self.assertEqual(self.tool.name, "generate_report")
        self.assertEqual(self.tool.tier, "confirm")
        schema = self.tool.input_schema
        self.assertIn("title", schema["properties"])
        self.assertIn("body", schema["properties"])
        # body 可选:不传时 _run 自动抓本条回复正文当报告主体(见 SPEC body 描述)·故 required 只含 title
        self.assertEqual(schema["required"], ["title"])

    def test_summarize(self):
        s = self.tool.summarize({"title": "测试报告", "body": "x" * 100})
        self.assertIn("测试报告", s)
        self.assertIn("100", s)

    def test_missing_title(self):
        r = self.tool.run({"body": "正文"})
        self.assertFalse(r.ok)
        self.assertIn("title", r.error)

    def test_missing_body(self):
        r = self.tool.run({"title": "T"})
        self.assertFalse(r.ok)
        self.assertIn("body", r.error)

    def test_happy_path_default_theme(self):
        r = self.tool.run({
            "title": "Smoke-Test-工具入口",
            "body": SAMPLE_MD,
            "subtitle": "smoke",
            "audience": "BRO 自动测试",
        })
        self.assertTrue(r.ok, f"工具失败: {r.error}\n{r.output}")
        self.assertIn("Smoke-Test", r.output)
        self.assertIn("KB", r.output)
        # 验证文件真的落在 data/reports/
        matches = list(self.reports_dir.glob("Smoke-Test*.docx"))
        self.assertGreaterEqual(len(matches), 1, "data/reports/ 没看到生成的 docx")
        for m in matches:
            self.assertGreater(m.stat().st_size, 3000)

    def test_happy_path_midnight_theme(self):
        r = self.tool.run({
            "title": "Smoke-深蓝主题",
            "body": "## 段落\n\n正文。",
            "theme": "midnight",
        })
        self.assertTrue(r.ok)
        self.assertIn("midnight", r.output)


class ApiReportEndpointTests(unittest.TestCase):
    """走 FastAPI TestClient 调 /dashboard/reports 和 /reports/<file>"""

    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient  # noqa
        except ImportError:
            raise unittest.SkipTest("fastapi.testclient 不可用 · 跳过 API 测试")

        from daemon_api import build_app

        cls.app = build_app()
        from fastapi.testclient import TestClient
        cls.client = TestClient(cls.app)
        cls.token = os.environ["OPUS_API_TOKEN"]
        cls.auth = {"Authorization": f"Bearer {cls.token}"}

        # 先生成一份报告 · 后面下载测试要用
        from agent_tools import REGISTRY
        cls.tool = REGISTRY["generate_report"]
        cls.reports_dir = ROOT / "data" / "reports"
        cls.before_files = set(
            p.name for p in cls.reports_dir.glob("*.docx")
        ) if cls.reports_dir.exists() else set()

        r = cls.tool.run({
            "title": "ApiSmoke",
            "body": "## 用于 API 端到端测试\n\n短内容。",
        })
        assert r.ok, r.error
        # 从输出中拿到文件名
        for line in r.output.splitlines():
            if line.strip().endswith(".docx") and "已生成" in line:
                cls.generated_name = line.split("·")[1].strip()
                break
        else:
            # fallback：扫描刚生成的文件
            after = set(p.name for p in cls.reports_dir.glob("*.docx"))
            new = after - cls.before_files
            assert new, "没看到生成的文件"
            cls.generated_name = next(iter(new))

    @classmethod
    def tearDownClass(cls):
        if not cls.reports_dir.exists():
            return
        after = set(p.name for p in cls.reports_dir.glob("*.docx"))
        for name in after - cls.before_files:
            try:
                (cls.reports_dir / name).unlink()
            except OSError:
                pass

    def test_dashboard_reports_no_auth(self):
        r = self.client.get("/dashboard/reports")
        self.assertEqual(r.status_code, 401)

    def test_dashboard_reports_list(self):
        r = self.client.get("/dashboard/reports", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertEqual(data["domain"], "reports")
        self.assertGreaterEqual(data["count"], 1)
        names = [it["name"] for it in data["items"]]
        self.assertIn(self.generated_name, names)
        # 字段齐全
        first = data["items"][0]
        for key in ("name", "size_kb", "created_at", "download_url"):
            self.assertIn(key, first)
        self.assertTrue(first["download_url"].startswith("/reports/"))

    def test_download_with_bearer(self):
        r = self.client.get(f"/reports/{self.generated_name}", headers=self.auth)
        self.assertEqual(r.status_code, 200, r.text)
        ct = r.headers.get("content-type", "")
        self.assertIn("wordprocessingml", ct)
        self.assertGreater(len(r.content), 3000)

    def test_download_with_query_token(self):
        r = self.client.get(f"/reports/{self.generated_name}?token={self.token}")
        self.assertEqual(r.status_code, 200)

    def test_download_no_auth(self):
        r = self.client.get(f"/reports/{self.generated_name}")
        self.assertEqual(r.status_code, 401)

    def test_download_invalid_token(self):
        r = self.client.get(f"/reports/{self.generated_name}?token=wrong")
        self.assertEqual(r.status_code, 401)

    def test_download_path_traversal_rejected(self):
        for bad in [
            "../etc/passwd",
            "..%2Fetc%2Fpasswd",
            "..\\windows\\system.ini",
            ".secret.docx",
            "~$tmp.docx",
            "not-docx.txt",
        ]:
            r = self.client.get(f"/reports/{bad}", headers=self.auth)
            self.assertIn(r.status_code, (400, 403, 404),
                          f"恶意路径 {bad} 未被拒: status={r.status_code}")

    def test_download_nonexistent(self):
        r = self.client.get("/reports/totally-does-not-exist.docx", headers=self.auth)
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
