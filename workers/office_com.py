"""本机 Office / WPS COM 导出。没有软件时由调用方改走 OfficeCLI。"""
from __future__ import annotations

import re
from pathlib import Path

_PPT = ("PowerPoint.Application", "KWPP.Application")
_WORD = ("Word.Application", "KWPS.Application", "wps.Application")


def _dispatch_ex(progids: tuple[str, ...]):
    import win32com.client

    last: Exception | None = None
    for pid in progids:
        try:
            return win32com.client.DispatchEx(pid), pid
        except Exception as exc:
            last = exc
    raise RuntimeError(last or "no office app")


def _pngs(dest: Path) -> list[Path]:
    files = [p for p in dest.iterdir() if p.is_file() and p.suffix.lower() == ".png"]

    def key(p: Path) -> int:
        m = re.search(r"(\d+)", p.stem)
        return int(m.group(1)) if m else 10**9

    return sorted(files, key=key)


def normalize_pngs(dest: Path) -> list[Path]:
    files = _pngs(dest)
    out: list[Path] = []
    for i, p in enumerate(files, 1):
        target = dest / f"{i:03d}.png"
        if p.resolve() != target.resolve():
            if target.exists():
                target.unlink()
            p.rename(target)
        out.append(target)
    return out


def export_pptx(src: Path, dest: Path) -> None:
    import pythoncom

    pythoncom.CoInitialize()
    app = None
    pres = None
    try:
        app, _ = _dispatch_ex(_PPT)
        try:
            app.Visible = False
        except Exception:
            pass
        try:
            app.DisplayAlerts = 0
        except Exception:
            pass
        try:
            app.ShowWindowsInTaskbar = False
        except Exception:
            pass
        try:
            pres = app.Presentations.Open(str(src), True, False, False)
        except Exception:
            pres = app.Presentations.Open(str(src))
        dest.mkdir(parents=True, exist_ok=True)
        pres.Export(str(dest), "PNG", 1600, 900)
        pres.Close()
        pres = None
        if not normalize_pngs(dest):
            raise RuntimeError("pptx export produced no slides")
    finally:
        if pres is not None:
            try:
                pres.Close()
            except Exception:
                pass
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def export_docx(src: Path, pdf: Path) -> None:
    import pythoncom

    pythoncom.CoInitialize()
    app = None
    doc = None
    try:
        app, _ = _dispatch_ex(_WORD)
        try:
            app.DisplayAlerts = 0
            app.Visible = False
        except Exception:
            pass
        try:
            doc = app.Documents.Open(str(src), False, True)
        except Exception:
            doc = app.Documents.Open(str(src))
        pdf.parent.mkdir(parents=True, exist_ok=True)
        try:
            doc.ExportAsFixedFormat(str(pdf), 17)
        except Exception:
            doc.SaveAs(str(pdf), 17)
        doc.Close(False)
        doc = None
        if not pdf.is_file() or pdf.stat().st_size <= 0:
            raise RuntimeError("docx export produced no pdf")
    finally:
        if doc is not None:
            try:
                doc.Close(False)
            except Exception:
                pass
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()
