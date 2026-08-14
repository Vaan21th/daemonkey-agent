"""
续跑 embedding 回填 · 只补 NULL 的 · 限速防限流 (wish-45b8ff04)
================================================================
第一次全量回填死在 ~96% (疑似智谱 429 限流) · 这个是续跑:
  - 只处理 embedding IS NULL 的 chunk
  - 每批后 sleep 0.5s 限速
  - 单批失败重试 2 次 (间隔 2s)
  - 跑完打印最终覆盖统计
"""
from __future__ import annotations

import sys
import time

sys.path.insert(0, ".")
from workers.memory_index import _get_conn, embed_where_sql
from workers.memory_embed import backfill_all, stats, embed_texts, _vec_to_blob  # noqa: F401

import numpy as np
import sqlite3


def retry_backfill(conn: sqlite3.Connection, max_batches: int = 200) -> tuple[int, int]:
    """带重试 + 限速的回填。"""
    rows = conn.execute(
        f"SELECT id, content FROM memory_chunks WHERE embedding IS NULL AND {embed_where_sql()}"
    ).fetchall()
    print(f"[resume] 待回填 {len(rows)} 条", flush=True)
    if not rows:
        return 0, 0
    ok = fail = 0
    batch_size = 32  # 智谱 embedding-3 实测上限 32 (64 报 400)
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        texts = [r[1][:4000] for r in batch]
        embs = None
        for attempt in range(3):
            embs = embed_texts(texts)
            if embs is not None:
                break
            time.sleep(2 * (attempt + 1))
        if embs is None:
            # 降级: 逐条用更短截断 (2000) 重试 · 极少数 chunk 含 API 拒收字符
            for (cid, content) in batch:
                sub_ok = False
                for cut in (2000, 1000, 500):
                    e = embed_texts([content[:cut]])
                    if e is not None:
                        conn.execute("UPDATE memory_chunks SET embedding=? WHERE id=?",
                                     (_vec_to_blob(np.asarray(e[0], dtype=np.float32)), cid))
                        ok += 1
                        sub_ok = True
                        break
                    time.sleep(1)
                if not sub_ok:
                    fail += 1
            conn.commit()
            continue
        for (cid, _), e in zip(batch, embs):
            conn.execute("UPDATE memory_chunks SET embedding=? WHERE id=?",
                         (_vec_to_blob(np.asarray(e, dtype=np.float32)), cid))
            ok += 1
        conn.commit()
        time.sleep(1.5)  # 限速防 429 (智谱 embedding-3 有速率限制 · 实测 1.5s 间隔稳定)
        if (i // batch_size) % 8 == 0:
            print(f"  ...{ok} 条", flush=True)
    return ok, fail


if __name__ == "__main__":
    conn = _get_conn()
    ok, fail = retry_backfill(conn)
    print(f"[resume] DONE ok={ok} fail={fail} · {stats(conn)}", flush=True)
    conn.close()
