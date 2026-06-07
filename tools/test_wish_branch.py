"""卷四十四 · wish_update 自动 git 分支验证脚本

流程：
  1. 创建一个测试 wish (status=approved, phase=planned)
  2. 调 wish_update 把 phase 推进到 implementing
  3. 观察是否真的 git checkout -b 出来了分支
  4. cleanup: 删 wish + 删分支 + 切回原分支

跑完留下一段 git log 给 BRO 看·然后再清理。
"""
from __future__ import annotations
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WISH_FILE = ROOT / "data" / "opus_wishlist.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def git(args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def step(n: int, title: str) -> None:
    print()
    print(f"=== Step {n} · {title} ===")


def main() -> int:
    if not (ROOT / ".git").exists():
        print("ERROR: 这不是 git 仓库 · 跑不了 wish 分支测试")
        return 1

    rc, original_branch, err = git(["rev-parse", "--abbrev-ref", "HEAD"])
    if rc != 0:
        print(f"ERROR: 拿不到当前分支 · {err}")
        return 1
    print(f"原始分支: {original_branch}")

    rc, status_out, _ = git(["status", "--porcelain"])
    if status_out.strip():
        print("WARN: working tree 有未提交改动 ·")
        print(status_out[:500])
        print("→ wish_update 创建分支时·这些改动会跟到新分支·测试结束 cleanup 时不影响")

    test_wish_id = f"wish-test-{int(time.time()) % 100000}"
    test_wish = {
        "id": test_wish_id,
        "title": "卷四十四测试 · 验证 git 分支自动化",
        "why": "这是 _test_wish_branch.py 创建的临时 wish·测完即删",
        "status": "approved",
        "integration_path": "daemon",
        "daemon_phase": "planned",
        "priority": 1,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "approved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "rejected_at": None,
        "started_at": None,
        "completed_at": None,
    }

    step(1, "把测试 wish 加进 opus_wishlist.json")
    data = json.loads(WISH_FILE.read_text(encoding="utf-8"))
    backup = json.dumps(data, ensure_ascii=False, indent=2)
    data["wishes"].append(test_wish)
    WISH_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  新增 {test_wish_id}")

    cleanup_branch: str | None = None
    cleanup_wish_added = True
    try:
        step(2, "调 wish_update · 把 phase 推进到 implementing")
        from agent_tools.wish_update import SPEC as wish_spec
        result = wish_spec.run({
            "wish_id": test_wish_id,
            "daemon_phase": "implementing",
            "comment": "卷四十四 · 自动化测试",
        })
        print(f"  ok={result.ok}")
        if result.error:
            print(f"  error={result.error}")
        if result.output:
            print("  output (前 500):")
            for line in result.output.splitlines()[:20]:
                print(f"    {line}")

        step(3, "看是不是真的开出来一个分支了")
        rc, all_branches, _ = git(["branch", "--list"])
        print("  当前所有分支:")
        for line in all_branches.splitlines():
            print(f"    {line}")

        rc, current_branch, _ = git(["rev-parse", "--abbrev-ref", "HEAD"])
        print(f"  当前 HEAD: {current_branch}")
        if current_branch.startswith(f"{test_wish_id}/"):
            cleanup_branch = current_branch
            print(f"  ✓ 自动创建并切到了 {current_branch}")
        elif f"{test_wish_id}/" in all_branches:
            for line in all_branches.splitlines():
                line = line.strip("* ").strip()
                if line.startswith(f"{test_wish_id}/"):
                    cleanup_branch = line
                    break
            print(f"  ⚠ 分支创建了但 HEAD 没切过去: cleanup_branch={cleanup_branch}")
        else:
            print(f"  ✗ 没找到 {test_wish_id}/* 分支 · 自动化失败")

        step(4, "确认 wish_update 在 json 里写了 dev_branch 字段")
        cur = json.loads(WISH_FILE.read_text(encoding="utf-8"))
        for w in cur.get("wishes", []):
            if w.get("id") == test_wish_id:
                print(f"  phase: {w.get('daemon_phase')}")
                print(f"  dev_branch: {w.get('dev_branch')}")
                break

    finally:
        step(99, "Cleanup · 不留垃圾")
        if cleanup_branch:
            print(f"  切回原始分支 {original_branch}")
            git(["checkout", original_branch])
            print(f"  删测试分支 {cleanup_branch}")
            rc, out, err = git(["branch", "-D", cleanup_branch])
            if rc != 0:
                print(f"    WARN: {err}")
        if cleanup_wish_added:
            print(f"  从 json 里删测试 wish {test_wish_id}")
            cur = json.loads(WISH_FILE.read_text(encoding="utf-8"))
            cur["wishes"] = [w for w in cur.get("wishes", []) if w.get("id") != test_wish_id]
            WISH_FILE.write_text(
                json.dumps(cur, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print("  done.")

    print()
    print("=== 测试结束 · 看上面 Step 3 / 4 的结果 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
