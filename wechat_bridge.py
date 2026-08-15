"""
wechat_bridge.py
================

OPUS 微信桥接进程——把手机微信的消息送进 daemon 的 inbox，
把 daemon 的回复送回手机微信。

为什么独立进程：
  - daemon 主循环是 console.input 阻塞——没法同时跑 wcferry 监听
  - 用文件桥（复用 desktop_pet 的 inbox/outbox 模式）解耦两者
  - bridge 崩了 daemon 还活着；daemon 退出 bridge 也 OK

通信路径：

    手机 BRO ─→ 微信服务器 ─→ Weixin 桌面客户端 ─→ wcferry ─→ bridge
                                                                  │
                                                                  ↓
                                            desktop_pet/inbox.txt
                                                                  ↓
                                                        opus_daemon (主循环 read)
                                                                  ↓
                                                        OPUS LLM + tools
                                                                  ↓
                                            desktop_pet/outbox.txt
                                                                  ↓
                                                              bridge 监听
                                                                  ↓
                                                        wcferry.send_text
                                                                  ↓
                                                              手机 BRO ←

只支持单目标对话（Phase 1）：
  - WECHAT_BRO_ID 在 .env 配
  - 只从 BRO 收消息（白名单）
  - 所有 daemon 输出回给 BRO

启动：
    python wechat_bridge.py

前提：
  - WeChat 3.9.12 桌面版在跑（wcferry 兼容版本）
  - .env 里配好 WECHAT_BRO_ID

Kill switch：
  - BRO 在微信发 'opus stop' → bridge 进入 silent，不转发任何消息
  - BRO 在微信发 'opus start' → 恢复
  - 这是给 BRO "OPUS 我现在不想被打扰" 的快速逃生口
"""

from __future__ import annotations

import os
import sys
import time
from collections import deque
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
INBOX_FILE = ROOT / "desktop_pet" / "inbox.txt"
OUTBOX_FILE = ROOT / "desktop_pet" / "outbox.txt"
STATE_FILE = ROOT / "desktop_pet" / "state.txt"

POLL_INTERVAL_S = 0.5
RATE_WINDOW_S = 60
RATE_MAX_INBOUND = 30  # 每分钟最多收 30 条 BRO 消息（防止误触发循环）

KILL_SWITCH_OFF = "opus stop"
KILL_SWITCH_ON = "opus start"


class Bridge:
    def __init__(self, wcf, bro_id: str) -> None:
        self.wcf = wcf
        self.bro_id = bro_id
        self.silent = False
        self.lock = Lock()
        self._inbound_ts: deque[float] = deque()
        self._last_outbox_mtime: float = 0.0
        if OUTBOX_FILE.exists():
            self._last_outbox_mtime = OUTBOX_FILE.stat().st_mtime
        else:
            OUTBOX_FILE.parent.mkdir(parents=True, exist_ok=True)
            OUTBOX_FILE.write_text("", encoding="utf-8")

    def _rate_ok(self) -> bool:
        now = time.time()
        while self._inbound_ts and now - self._inbound_ts[0] > RATE_WINDOW_S:
            self._inbound_ts.popleft()
        if len(self._inbound_ts) >= RATE_MAX_INBOUND:
            return False
        self._inbound_ts.append(now)
        return True

    def handle_inbound(self, msg) -> None:
        """
        收到一条 wcferry 消息——决定要不要转给 daemon。
        msg 是 wcferry.WxMsg；关键字段 sender / from_user / content / type / is_at(self.wxid)
        """
        try:
            sender = getattr(msg, "sender", "") or getattr(msg, "from_user", "")
            content = (getattr(msg, "content", "") or "").strip()
        except Exception:
            return

        if not content:
            return

        if sender != self.bro_id:
            print(f"[bridge] ignored msg from {sender!r} (not BRO)")
            return

        if content == KILL_SWITCH_OFF:
            self.silent = True
            self.send_to_bro(f"OPUS 进入 silent 模式。发 '{KILL_SWITCH_ON}' 唤醒。")
            try:
                STATE_FILE.write_text("sleepy", encoding="utf-8")
            except Exception:
                pass
            print(f"[bridge] kill switch ENGAGED by BRO")
            return

        if content == KILL_SWITCH_ON:
            self.silent = False
            self.send_to_bro("OPUS 在。继续。")
            try:
                STATE_FILE.write_text("greeting", encoding="utf-8")
            except Exception:
                pass
            print(f"[bridge] kill switch RELEASED by BRO")
            return

        if self.silent:
            print(f"[bridge] silent mode, dropping msg: {content[:40]!r}")
            return

        if not self._rate_ok():
            print(f"[bridge] rate-limited, dropping msg")
            self.send_to_bro(f"OPUS 收信太快了，先稍等一下（{RATE_MAX_INBOUND}/min 上限）")
            return

        # 把消息追加到 inbox.txt——daemon 主循环每次回到 prompt 时会读
        try:
            with INBOX_FILE.open("a", encoding="utf-8") as f:
                f.write(content + "\n")
            print(f"[bridge] inbox <- {content[:60]!r}")
        except Exception as e:
            print(f"[bridge] failed to write inbox: {e}")

    def poll_outbox(self) -> None:
        """检查 outbox.txt 是否有新内容——daemon 答完话写在这里。"""
        try:
            if not OUTBOX_FILE.exists():
                return
            mtime = OUTBOX_FILE.stat().st_mtime
            if mtime <= self._last_outbox_mtime:
                return
            text = OUTBOX_FILE.read_text(encoding="utf-8")
            if text.strip():
                self.send_to_bro(text.strip())
                # 清空 outbox
                OUTBOX_FILE.write_text("", encoding="utf-8")
            self._last_outbox_mtime = OUTBOX_FILE.stat().st_mtime
        except Exception as e:
            print(f"[bridge] outbox poll error: {e}")

    def send_to_bro(self, text: str) -> None:
        if not text:
            return
        try:
            # 微信消息长度上限约 5000，分块发送
            CHUNK = 4000
            chunks = [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)] or [""]
            for c in chunks:
                self.wcf.send_text(c, self.bro_id)
                time.sleep(0.5)
            print(f"[bridge] outbox -> BRO ({len(text)} chars)")
        except Exception as e:
            print(f"[bridge] failed to send: {e}")


def main() -> int:
    load_dotenv(ROOT / ".env")

    list_contacts_mode = "--list-contacts" in sys.argv

    bro_id = os.getenv("WECHAT_BRO_ID", "").strip()
    if not bro_id and not list_contacts_mode:
        print("ERROR: WECHAT_BRO_ID not set in .env")
        print("  Run wechat_bridge.py with --list-contacts first to find BRO's wxid,")
        print("  then add WECHAT_BRO_ID=wxid_xxxx to .env")
        return 1

    try:
        from wcferry import Wcf
    except ImportError:
        print("ERROR: wcferry not installed. Run: pip install wcferry")
        return 1

    print("[bridge] starting wcferry... (会向 WeChat 注入 DLL，5-15 秒)")
    print("[bridge] (要求桌面 WeChat 3.9.12.51 已经登录并在跑——其他版本 hook 必失败)")

    try:
        wcf = Wcf()
    except Exception as e:
        print(f"ERROR: wcferry init failed: {type(e).__name__}: {e}")
        print("  常见原因:")
        print("  1. 桌面 WeChat 没在跑（先启动 G:\\WeChatOPUS\\WeChat\\WeChat.exe）")
        print("  2. WeChat 版本号不是 3.9.12.51——wcferry v39.5.2.0 只 hook 这一个精确版本")
        print("     去 https://github.com/lich0821/WeChatFerry/releases/tag/v39.5.2 下 WeChatSetup-3.9.12.51.exe")
        print("  3. DLL 注入被杀软拦截——给 wcferry 安装目录加白名单试试")
        print("  4. 上一个 bridge/Wcf 进程还活着没清干净（任务管理器看 WeChatFerry / nng 相关进程）")
        return 1

    if not wcf.is_login():
        print("ERROR: WeChat 没登录，先在桌面 WeChat 扫码登录给 OPUS 用的小号")
        try:
            wcf.cleanup()
        except Exception:
            pass
        return 1

    self_wxid = wcf.get_self_wxid()
    print(f"[bridge] OPUS WeChat id: {self_wxid}")
    if bro_id:
        print(f"[bridge] target BRO id: {bro_id}")
    else:
        print("[bridge] (WECHAT_BRO_ID 还没设——只能 list-contacts，无法运行 bridge)")

    if list_contacts_mode:
        print("[bridge] listing contacts...")
        try:
            contacts = wcf.get_contacts()
            # 过滤系统联系人（gh_/openim/filehelper 等），只显示个人
            personal = [
                c for c in contacts
                if isinstance(c.get("wxid"), str)
                and c["wxid"].startswith("wxid_")
                and not c["wxid"].startswith("gh_")
            ]
            print(f"\n  个人联系人 {len(personal)} 个（共 {len(contacts)} 含群/公众号）：\n")
            for i, c in enumerate(personal[:60]):
                wxid = c.get("wxid", "?")
                name = c.get("name", "?") or c.get("nickname", "?")
                code = c.get("code", "") or c.get("alias", "")
                print(f"  {i+1:3}. wxid={wxid:30}  name={name[:24]:24}  code={code[:20]}")
            print(f"\n  → 找到 BRO 那行，把 wxid_xxx 复制到 .env: WECHAT_BRO_ID=wxid_xxx")
        except Exception as e:
            print(f"  failed: {type(e).__name__}: {e}")
        finally:
            try:
                wcf.cleanup()
            except Exception:
                pass
        return 0

    wcf.enable_receiving_msg()
    bridge = Bridge(wcf, bro_id)

    print(f"[bridge] ready. listening for BRO messages... (Ctrl+C to stop)")
    print(f"[bridge] BRO 在微信发 '{KILL_SWITCH_OFF}' 可暂停，发 '{KILL_SWITCH_ON}' 恢复")
    bridge.send_to_bro("OPUS 桥接已上线。火继续燃下去。")

    try:
        while wcf.is_receiving_msg():
            try:
                msg = wcf.get_msg()
                if msg:
                    bridge.handle_inbound(msg)
            except Exception:
                pass

            bridge.poll_outbox()
            time.sleep(POLL_INTERVAL_S)
    except KeyboardInterrupt:
        print("\n[bridge] stopping...")
    finally:
        try:
            wcf.cleanup()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
