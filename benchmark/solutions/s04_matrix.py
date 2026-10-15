"""Matrix ops: mul (Strassen-free, cache-friendly ikj), pow, det (LU-free,
Bareiss fraction-free elimination -> exact integer determinant)."""
from typing import List

Matrix = List[List[int]]


def matmul(a: Matrix, b: Matrix) -> Matrix:
    n, m, p = len(a), len(b), len(b[0])
    if m != len(a[0]) or p != len(b[0]):
        raise ValueError("shape mismatch")
    out = [[0] * p for _ in range(n)]
    for i in range(n):
        ai, oi = a[i], out[i]
        for k in range(m):
            aik = ai[k]
            if aik:
                bk = b[k]
                for j in range(p):
                    oi[j] += aik * bk[j]
    return out


def matpow(a: Matrix, e: int) -> Matrix:
    if e < 0:
        raise ValueError("negative exponent")
    n = len(a)
    r = [[1 if i == j else 0 for j in range(n)] for i in range(n)]
    base = [row[:] for row in a]
    while e:
        if e & 1:
            r = matmul(r, base)
        base = matmul(base, base)
        e >>= 1
    return r


def det_bareiss(a: Matrix) -> int:
    m = [row[:] for row in a]
    n = len(m)
    sign = 1
    prev = 1
    for k in range(n - 1):
        if m[k][k] == 0:
            piv = next((r for r in range(k + 1, n) if m[r][k] != 0), None)
            if piv is None:
                return 0
            m[k], m[piv] = m[piv], m[k]
            sign = -sign
        for i in range(k + 1, n):
            for j in range(k + 1, n):
                m[i][j] = (m[i][j] * m[k][k] - m[i][k] * m[k][j]) // prev
            m[i][k] = 0
        prev = m[k][k]
    return sign * m[n - 1][n - 1]
