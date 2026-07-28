"""Benchmark FindArtist (regex) vs FindArtistV2 (str.find).

Usage:
    python benchmark/bench_find_artist.py
"""

import random
import re
import string
import sys
import timeit
from pathlib import Path

sys.path.insert(0, ".")
from autoclassfiy import FindArtist, FindArtistV2

# ═══════════════════════════════════════════════════════════════
# 基础测试用例
# ═══════════════════════════════════════════════════════════════
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
    Path("[some very long artist name here] Title (2024).zip"),
    Path(
        "[group_name (artist_name_with_underscores)] Long Title Here 01 (digital).zip"
    ),
]


# ═══════════════════════════════════════════════════════════════
# 原始函数（无 lru_cache，无 IgnoredArtist 递归）
# ═══════════════════════════════════════════════════════════════
def _raw_v1(name: str) -> str:
    ret = re.search(r"\[(.*?)\]", name)
    if not ret:
        return ""
    inner = re.search(r"\((.*?)\)", ret.group(1))
    return (inner.group(1) if inner else ret.group(1)).strip()


def _raw_v2(name: str) -> str:
    start = name.find("[")
    if start == -1:
        return ""
    end = name.find("]", start + 1)
    if end == -1:
        return ""
    in_b = name[start + 1 : end]
    p = in_b.find("(")
    return (in_b[p + 1 : in_b.find(")", p)] if p != -1 else in_b).strip()


# ═══════════════════════════════════════════════════════════════
# Fuzz 生成器
# ═══════════════════════════════════════════════════════════════
CHARS_ASCII = string.ascii_letters + string.digits + " _-."
CHARS_UNICODE = "中文日本語한국어éÜñ🌟"

FUZZ_ARTISTS = [
    "akira",
    "alice_soft",
    "digital_lover",
    "shimanto",
    "type-g",
    "a",
    "ab",  # 极短
    "x" * 50,  # 极长
]
FUZZ_GROUPS = [
    "choco",
    "nakajima_yuka",
    "kobuichi",
    "",
    "",
    "z" * 30,  # 极长 group
]


def _rand_str(chars: str, min_len: int = 1, max_len: int = 40) -> str:
    return "".join(random.choices(chars, k=random.randint(min_len, max_len)))


def _fuzz_valid() -> str:
    """生成合法格式的文件名：带 [...] 或 [group (artist)]。"""
    a = random.choice(FUZZ_ARTISTS)
    title = _rand_str(CHARS_ASCII, 5, 30) + random.choice([".zip", ".rar", ".7z", ""])

    if random.random() < 0.5:
        # [Artist] Title
        return f"[{a}] {title}"

    g = random.choice(FUZZ_GROUPS)
    if random.random() < 0.5:
        # [Artist (Group)] Title — V1/V2 返回 Group
        return f"[{a} ({g})] {title}"
    else:
        # [Group (Artist)] Title — V1/V2 返回 Artist
        return f"[{g} ({a})] {title}"


def _fuzz_edge() -> str:
    """生成边界/畸形输入。"""
    kind = random.randint(0, 14)
    rand = lambda: _rand_str(CHARS_ASCII, 1, 20)
    u = lambda: _rand_str(CHARS_UNICODE, 1, 8)

    if kind == 0:
        return ""  # 空字符串
    if kind == 1:
        return rand()  # 纯文本，无括号
    if kind == 2:
        return "[" + rand()  # 只有 [
    if kind == 3:
        return rand() + "]"  # 只有 ]
    if kind == 4:
        return "][" + rand()  # 反转括号
    if kind == 5:
        return "[[" + rand() + "]]"  # 嵌套括号 [[...]]
    if kind == 6:
        return "[(" + rand() + ")] " + rand()  # 括号内只有 (...) 无文本
    if kind == 7:
        return "[" + rand() + " (" + rand() + ")] " + rand()  # 两个括号对
    if kind == 8:
        return "[] " + rand()  # 空括号
    if kind == 9:
        return "[" + rand() + "()] " + rand()  # 空括号内的 ()
    if kind == 10:
        return "[(" + u() + ")] " + rand()  # unicode 艺术名
    if kind == 11:
        return "[" + u() + "] " + rand()  # unicode 无 group
    if kind == 12:
        return "[" + rand() + " (" + u() + ")] " + rand()  # unicode group
    if kind == 13:
        return "[" + " " * random.randint(1, 10) + rand() + "] " + rand()  # 前导空格
    if kind == 14:
        return _rand_str(CHARS_ASCII, 100, 200)  # 超长随机字符串
    return rand()


def generate_fuzz_corpus(size: int = 5000) -> list[str]:
    """生成 fuzz 测试语料，混合合法与边界输入。"""
    corpus = []
    for _ in range(size // 2):
        corpus.append(_fuzz_valid())
        corpus.append(_fuzz_edge())
    return corpus


# ═══════════════════════════════════════════════════════════════
# 简单随机文件名（性能测试用）
# ═══════════════════════════════════════════════════════════════
ARTISTS = ["akira", "alice_soft", "digital_lover", "shimanto", "type-g"]
GROUPS = ["choco", "nakajima_yuka", "kobuichi", "", ""]


def _rand_name() -> str:
    a = random.choice(ARTISTS)
    g = random.choice(GROUPS)
    title = "".join(random.choices(string.ascii_letters, k=random.randint(5, 20)))
    if g:
        return f"[{a} ({g})] {title}.zip"
    return f"[{a}] {title}.zip"


# ═══════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════
def main() -> None:
    # ── 1. 基础正确性 ──────────────────────────────────────
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

    # ── 2. Fuzz 正确性 ─────────────────────────────────────
    print()
    print("=" * 60)
    print("2. Fuzz correctness (50000 random + edge cases)")
    print("=" * 60)
    fuzz = generate_fuzz_corpus(50000)
    mismatches: list[tuple[str, str, str]] = []
    for name in fuzz:
        v1 = _raw_v1(name)
        v2 = _raw_v2(name)
        if v1 != v2:
            mismatches.append((name, v1, v2))
    if mismatches:
        print(f"  FAIL: {len(mismatches)} mismatches found!")
        for name, v1, v2 in mismatches[:10]:
            print(f"    {name!r:60s}  v1={v1!r:25s}  v2={v2!r:25s}")
        if len(mismatches) > 10:
            print(f"    ... and {len(mismatches) - 10} more")
    else:
        print(f"  All {len(fuzz)} cases OK")

    # ── 3. 缓存命中性能 ────────────────────────────────────
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

    # ── 4. 冷调用性能（简单随机） ──────────────────────────
    print()
    print("=" * 60)
    print("4. Raw performance (no cache, 100000 simple items)")
    print("=" * 60)
    bulk = [_rand_name() for _ in range(100000)]
    t1 = timeit.timeit(lambda: [_raw_v1(n) for n in bulk], number=1)
    t2 = timeit.timeit(lambda: [_raw_v2(n) for n in bulk], number=1)
    print(f"  raw V1 (regex): {t1 * 1000:.1f}ms for 100000 items")
    print(f"  raw V2 (str):   {t2 * 1000:.1f}ms for 100000 items")
    print(f"  -> raw V2 is {t1 / t2:.1f}x faster")

    # ── 5. 冷调用性能（fuzz 混合） ─────────────────────────
    print()
    print("=" * 60)
    print("5. Raw performance (no cache, 100000 fuzz items)")
    print("=" * 60)
    fuzz_perf = generate_fuzz_corpus(100000)
    t1 = timeit.timeit(lambda: [_raw_v1(n) for n in fuzz_perf], number=1)
    t2 = timeit.timeit(lambda: [_raw_v2(n) for n in fuzz_perf], number=1)
    print(f"  raw V1 (regex): {t1 * 1000:.1f}ms for 100000 items")
    print(f"  raw V2 (str):   {t2 * 1000:.1f}ms for 100000 items")
    print(f"  -> raw V2 is {t1 / t2:.1f}x faster")


if __name__ == "__main__":
    main()
