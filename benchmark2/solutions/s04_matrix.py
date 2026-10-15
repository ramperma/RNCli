"""Matrices enteras: multiplicacion ikj, potencia binaria y determinante
exacto por eliminacion de Bareiss (sin flotantes)."""
from typing import List

M = List[List[int]]


def mul(a: M, b: M) -> M:
    if not a or not b or len(a[0]) != len(b):
        raise ValueError("shape mismatch")
    n, k, p = len(a), len(b), len(b[0])
    out = [[0] * p for _ in range(n)]
    for i in range(n):
        row, orow = a[i], out[i]
        for kk in range(k):
            aik = row[kk]
            if aik:
                brow = b[kk]
                for j in range(p):
                    orow[j] += aik * brow[j]
    return out


def power(a: M, e: int) -> M:
    if e < 0:
        raise ValueError("negative exponent")
    n = len(a)
    acc = [[int(i == j) for j in range(n)] for i in range(n)]
    base = [r[:] for r in a]
    while e > 0:
        if e % 2 == 1:
            acc = mul(acc, base)
        base = mul(base, base)
        e //= 2
    return acc


def determinant(a: M) -> int:
    n = len(a)
    t = [r[:] for r in a]
    sign, prev = 1, 1
    for col in range(n - 1):
        if t[col][col] == 0:
            swap = next((r for r in range(col + 1, n) if t[r][col]), None)
            if swap is None:
                return 0
            t[col], t[swap] = t[swap], t[col]
            sign = -sign
        for r in range(col + 1, n):
            for c in range(col + 1, n):
                t[r][c] = (t[r][c] * t[col][col] - t[r][col] * t[col][c]) // prev
            t[r][col] = 0
        prev = t[col][col]
    return sign * t[n - 1][n - 1]
