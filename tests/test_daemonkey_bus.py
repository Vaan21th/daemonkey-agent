import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUS = ROOT / "static" / "daemonkey-bus.js"
CHAT = ROOT / "static" / "chat.js"
COMP = ROOT / "static" / "companion" / "companion.js"


def test_bus_on_emit_cancel():
    script = r"""
const fs = require('fs');
const vm = require('vm');
const ctx = { console, window: {} };
ctx.window = ctx;
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const DK = ctx.Daemonkey;
let seen = 0;
DK.on('view:switch', (ev) => { seen += 1; ev.view = 'mine'; });
const ok = DK.emit('view:switch', { view: 'home', previous: null });
if (!ok) { console.error('should continue'); process.exit(2); }
let blocked = 0;
DK.on('message:render', () => { blocked += 1; return false; });
const go = DK.emit('message:render', { phase: 'before' });
if (go) { console.error('should cancel'); process.exit(3); }
if (seen !== 1 || blocked !== 1) { console.error('count', seen, blocked); process.exit(4); }
console.log('ok');
"""
    r = subprocess.run(
        ["node", "-e", script, str(BUS)],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    assert "ok" in r.stdout


def test_official_emit_sites_exist():
    chat = CHAT.read_text(encoding="utf-8")
    comp = COMP.read_text(encoding="utf-8")
    for name in ("message:render", "sse:event", "view:switch"):
        needle = f"Daemonkey.emit('{name}'"
        assert needle in chat, needle
        assert needle in comp, needle


def test_bus_file_promises_three_events():
    text = BUS.read_text(encoding="utf-8")
    assert "view:switch" in text
    assert "message:render" in text
    assert "sse:event" in text
    assert "DK.emit = function" in text
