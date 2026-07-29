"""Benchmark FindArtist (regex) vs FindArtistV2 (str.find).

Usage:
    python benchmark/bench_find_artist.py
"""

import random
import string
import sys
import timeit
from pathlib import Path

sys.path.insert(0, ".")
from autoclassfiy import FindArtist, FindArtistV2

# ---- 基础测试用例 ----

TEST_CASES: list[str | Path] = [
    Path("[akira] Komori-chan 1 (digital).zip"),
    Path("[alice_soft (choco)] Rance 01.zip"),
    Path("[digital lover (nakajima yuka)] D.L. action 01.zip"),
    Path("[shimanto] Boku to Sensei no Kazoku 1-2.zip"),
    Path("[type-g (kobuichi)] Secret Garden 01.zip"),
    Path("no_brackets_here.zip"),
    Path("[short] x.zip"),
    Path("[ Only left.zip"),
    Path(" Only right].zip"),
    Path("] Wrong order [abc.zip"),
    Path("] Wrong order [abc].zip"),
    Path("[some very long artist name here] Title (2024).zip"),
    Path("[group_name (artist_name)] Long Title Here 01 (digital).zip"),
]

# ---- Hypothesis fuzz ----

from hypothesis import given, settings
from hypothesis import strategies as st


@given(st.text(st.characters(blacklist_categories=("Cs",)), max_size=200))
@settings(max_examples=20000)
def _check_v1_v2_equal(name: str):
    assert FindArtist(name) == FindArtistV2(name), f"input={name!r}"


# ---- 性能测试用随机文件名 ----

ARTISTS = ["akira", "alice_soft", "digital_lover", "shimanto", "type-g"]
GROUPS = ["choco", "nakajima_yuka", "kobuichi", "", ""]


def _rand_name() -> str:
    a = random.choice(ARTISTS)
    g = random.choice(GROUPS)
    title = "".join(random.choices(string.ascii_letters, k=random.randint(5, 20)))
    if g:
        return f"[{a} ({g})] {title}.zip"
    return f"[{a}] {title}.zip"


# ---- main ----


def main() -> None:
    # 1. 基础正确性
    print("=" * 60)
    print("1. Correctness (fixed cases)")
    print("=" * 60)
    for c in TEST_CASES:
        v1 = FindArtist(c)
        v2 = FindArtistV2(c)
        ok = "OK" if v1 == v2 else "MISMATCH"
        print(f"  {ok:8s}  v1={v1!r:33s}  v2={v2!r:33s}  file={str(c)[:60]}")
        if v1 != v2:
            print(f"         ^^^ V1 != V2 on: {c!r}")

    # 2. Hypothesis fuzz
    print()
    print("=" * 60)
    print("2. Fuzz correctness (Hypothesis, 20000 random inputs)")
    print("=" * 60)
    _check_v1_v2_equal()

    # 3. 缓存命中性能
    print()
    print("=" * 60)
    print("3. Cached performance (lru_cache hit, 100000 rounds)")
    print("=" * 60)
    N = 100000
    t1 = timeit.timeit(lambda: [FindArtist(c) for c in TEST_CASES], number=N)
    t2 = timeit.timeit(lambda: [FindArtistV2(c) for c in TEST_CASES], number=N)
    print(f"  FindArtist   (regex): {t1:.4f}s  ({t1 / N * 1e6:.1f} us/call)")
    print(f"  FindArtistV2 (str):   {t2:.4f}s  ({t2 / N * 1e6:.1f} us/call)")
    print(f"  -> V2 is {t1 / t2:.1f}x faster")

    # 4. 冷调用性能（清除 lru_cache 后首次调用）
    print()
    print("=" * 60)
    print("4. Cold performance (cache cleared, 100000 simple items)")
    print("=" * 60)
    bulk = [_rand_name() for _ in range(100000)]
    FindArtistV2.cache_clear()
    t1 = timeit.timeit(lambda: [FindArtist(n) for n in bulk], number=1)
    FindArtistV2.cache_clear()
    t2 = timeit.timeit(lambda: [FindArtistV2(n) for n in bulk], number=1)
    print(f"  FindArtist   (regex): {t1 * 1000:.1f}ms for 100000 items")
    print(f"  FindArtistV2 (str):   {t2 * 1000:.1f}ms for 100000 items")
    print(f"  -> V2 is {t1 / t2:.1f}x faster")


if __name__ == "__main__":
    main()
