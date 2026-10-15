"""Correctness + throughput. Run: python benchmark2/test_suite.py"""
import random
import time

from solutions.s01_lru_cache import LRUCache
from solutions.s02_dijkstra import shortest_path
from solutions.s03_vcard import parse
from solutions.s04_matrix import mul, power, determinant


def test_lru():
    c = LRUCache(2)
    c.put(1, 1); c.put(2, 2)
    assert c.get(1) == 1
    c.put(3, 3)                      # evicts 2
    assert c.get(2) is None and c.get(3) == 3
    random.seed(7)
    ref: dict = {}
    order: list = []
    for _ in range(3000):
        k = random.randint(0, 10)
        if random.random() < 0.5:
            assert c.get(k) == ref.get(k)
            if k in order:
                order.remove(k); order.append(k)
        else:
            c.put(k, k)
            ref[k] = k
            if k in order:
                order.remove(k)
            order.append(k)
            if len(order) > 2:
                ref.pop(order.pop(0))


def test_dijkstra():
    g = {"a": {"b": 1, "c": 4}, "b": {"c": 2, "d": 5}, "c": {"d": 1}, "d": {}}
    path, cost = shortest_path(g, "a", "d")
    assert path == ["a", "b", "c", "d"] and cost == 4.0
    p, c0 = shortest_path(g, "a", "a")
    assert p == ["a"] and c0 == 0.0
    try:
        shortest_path({"a": {"b": -2}, "b": {}}, "a", "b")
        raise AssertionError("should have raised")
    except ValueError:
        pass


def test_vcard():
    p = parse("BEGIN:VCARD\nN;TYPE=X:Garcia\nNOTE:uno\n  dos\nEND:VCARD")
    assert p["N"] == "Garcia"
    assert p["NOTE"] == "uno dos"
    assert parse("x:1:2")["X"] == "1:2"


def test_matrix():
    A = [[1, 2], [3, 4]]
    assert mul(A, A) == [[7, 10], [15, 22]]
    assert power(A, 0) == [[1, 0], [0, 1]]
    assert power(A, 3) == [[37, 54], [81, 118]]
    assert determinant([[3, 0, 2], [-1, 8, -4], [2, 1, 6]]) == 122
    assert determinant([[0, 1], [1, 0]]) == -1
    assert determinant([[1, 2], [2, 4]]) == 0


def bench():
    n = 120
    A = [[random.randint(-9, 9) for _ in range(n)] for _ in range(n)]
    t0 = time.perf_counter()
    r = A
    for _ in range(3):
        r = mul(r, A)
    dt = time.perf_counter() - t0
    t1 = time.perf_counter()
    c = LRUCache(1000)
    for i in range(200_000):
        k = random.randrange(5000)
        c.get(k) if i % 3 else c.put(k, i)
    dt2 = time.perf_counter() - t1
    return 2 * n ** 3 * 3 / dt / 1e6, 200_000 / dt2 / 1e6


if __name__ == "__main__":
    for fn in (test_lru, test_dijkstra, test_vcard, test_matrix):
        fn()
    mops, lru = bench()
    print(f"ALL TESTS PASSED | matmul: {mops:.1f} Mops/s | LRU: {lru:.2f} Mops/s")
