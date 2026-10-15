"""Verifica correctness + throughput. Run: python -m pytest benchmark/test_suite.py -q
or simply: python benchmark/test_suite.py"""
import random
import time

from solutions.s01_lru_cache import LRUCache
from solutions.s02_dijkstra import dijkstra
from solutions.s03_rfc3986 import parse_vcard
from solutions.s04_matrix import matmul, matpow, det_bareiss


def test_lru():
    c = LRUCache(3)
    for i in range(3):
        c.put(i, i * 10)
    assert c.get(0) == 0
    c.put(3, 30)                      # evicts 1 (LRU)
    assert c.get(1) is None
    assert len(c) == 3
    # random ops vs reference model
    ref = {}
    order = []
    c = LRUCache(3)  # fresh cache so it matches the empty reference model
    random.seed(1)
    for _ in range(2000):
        k = random.randint(0, 10)
        if random.random() < 0.5:
            v = c.get(k)
            assert v == ref.get(k)
            if k in order:
                order.remove(k); order.append(k)
        else:
            c.put(k, k)
            ref[k] = k
            if k in order:
                order.remove(k)
            order.append(k)
            if len(order) > 3:
                old = order.pop(0)
                ref.pop(old, None)
    assert len(c) == len(ref)


def test_dijkstra():
    g = {"a": {"b": 1, "c": 4}, "b": {"c": 2, "d": 5}, "c": {"d": 1}, "d": {}}
    path, cost = dijkstra(g, "a", "d")
    assert path == ["a", "b", "c", "d"] and cost == 4.0
    p2, c2 = dijkstra(g, "a", "zzz" if False else "a")
    assert p2 == ["a"] and c2 == 0.0
    try:
        dijkstra({"a": {"b": -1}, "b": {}}, "a", "b")
        assert False
    except ValueError:
        pass


def test_vcard():
    txt = "BEGIN:VCARD\nNAME:Juan\nDESC:line one\n  line two\nEND:VCARD"
    p = parse_vcard(txt)
    assert p["NAME"] == "Juan" and p["DESC"] == "line one line two"
    assert parse_vcard("n:a;b:c")["N"] == "a;b:c"


def test_matrix():
    A = [[1, 2], [3, 4]]
    assert matmul(A, A) == [[7, 10], [15, 22]]
    assert matpow(A, 0) == [[1, 0], [0, 1]]
    assert matpow(A, 3) == [[37, 54], [81, 118]]
    M = [[3, 0, 2], [-1, 8, -4], [2, 1, 6]]
    assert det_bareiss(M) == 122  # cofactor: 3*52 + 2*(-17)
    # pivot-less zero row
    assert det_bareiss([[1, 2], [2, 4]]) == 0
    # swap case
    assert det_bareiss([[0, 1], [1, 0]]) == -1


def bench():
    t0 = time.perf_counter()
    n = 120
    A = [[random.randint(-9, 9) for _ in range(n)] for _ in range(n)]
    r = 0
    for _ in range(3):
        r = matmul(r or A, A)
    dt = time.perf_counter() - t0
    ops = 2 * n ** 3 * 3
    t1 = time.perf_counter()
    c = LRUCache(1000)
    for i in range(200_000):
        k = random.randrange(5000)
        if i % 3:
            c.get(k)
        else:
            c.put(k, i)
    dt2 = time.perf_counter() - t1
    return ops / dt / 1e6, 200_000 / dt2 / 1e6


if __name__ == "__main__":
    for fn in (test_lru, test_dijkstra, test_vcard, test_matrix):
        fn()
    mops, lru_mops = bench()
    print(f"ALL TESTS PASSED | matmul: {mops:.1f} Mops/s | LRU: {lru_mops:.2f} Mops/s")
