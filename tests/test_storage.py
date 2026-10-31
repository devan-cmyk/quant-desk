"""Atomic JSON writes — a concurrent reader (e.g. the always-on dashboard) must never see a
torn/partial file while a scheduled agent is writing it."""
import json
import os
import threading
import time

from quant_desk.storage import atomic_write_json


def test_roundtrip_and_no_tmp_left(tmp_path):
    p = str(tmp_path / "s.json")
    atomic_write_json(p, {"a": 1, "b": [1, 2, 3]})
    assert json.load(open(p)) == {"a": 1, "b": [1, 2, 3]}
    assert [f for f in os.listdir(tmp_path) if ".tmp" in f] == []     # temp cleaned up


def test_overwrite_replaces_atomically(tmp_path):
    p = str(tmp_path / "s.json")
    atomic_write_json(p, {"v": 1})
    atomic_write_json(p, {"v": 2})
    assert json.load(open(p))["v"] == 2


def test_concurrent_reads_never_tear(tmp_path):
    p = str(tmp_path / "s.json")
    atomic_write_json(p, {"x": list(range(3000))})
    stop = {"v": False}; torn = {"v": 0}; reads = {"v": 0}

    def writer():
        while not stop["v"]:
            atomic_write_json(p, {"x": list(range(3000))})

    def reader():
        while not stop["v"]:
            try:
                json.load(open(p)); reads["v"] += 1
            except Exception:
                torn["v"] += 1

    ts = [threading.Thread(target=writer), threading.Thread(target=reader)]
    [t.start() for t in ts]; time.sleep(0.8); stop["v"] = True; [t.join() for t in ts]
    assert reads["v"] > 0          # actually exercised concurrent reads
    assert torn["v"] == 0          # and none of them saw a partial file



def test_overlapping_writers_use_distinct_temporary_files(tmp_path, monkeypatch):
    import quant_desk.storage as storage
    from concurrent.futures import ThreadPoolExecutor
    barrier = threading.Barrier(2)
    original_replace = storage.os.replace

    def synchronized_replace(src, dst):
        barrier.wait(timeout=5)
        return original_replace(src, dst)

    monkeypatch.setattr(storage.os, "replace", synchronized_replace)
    target = str(tmp_path / "shared.json")
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda i: atomic_write_json(target, {"writer": i}), range(2)))
    assert json.loads((tmp_path / "shared.json").read_text()) in ({"writer": 0}, {"writer": 1})
    assert list(tmp_path.iterdir()) == [tmp_path / "shared.json"]
