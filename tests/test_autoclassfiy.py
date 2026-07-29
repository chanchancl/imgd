import re

from hypothesis import assume, given
from hypothesis import strategies as st

from autoclassfiy import FindArtist, FindArtistV2

CHARS = st.characters(blacklist_categories=("Cs",))

# 只用 hex 字符生成作者名，不可能命中 IgnoredArtist（全是自然语言词汇）
_SAFE = st.text(
    st.characters(whitelist_categories=("N",), whitelist_characters="abcdef"),
    min_size=1,
    max_size=20,
)


@st.composite
def _simple_input(draw):
    """生成 [artist] title，expected = artist。"""
    artist = draw(_SAFE)
    title = draw(st.text(CHARS, max_size=30))
    return f"[{artist}] {title}", artist


@st.composite
def _group_input(draw):
    """生成 [group (artist)] title 或 [artist (group)]，expected = 括号内的名字。"""
    a = draw(_SAFE)
    b = draw(_SAFE)
    if draw(st.booleans()):
        return f"[{a} ({b})] title", b
    else:
        return f"[{b} ({a})] title", a


@st.composite
def _no_bracket_input(draw):
    """生成不带 [...] 的输入，expected = ''。"""
    s = draw(st.text(CHARS, max_size=50))
    assume(not re.search(r"\[.*?\]", s))
    return s, ""


INPUT_AND_EXPECTED = st.one_of(_simple_input(), _group_input(), _no_bracket_input())


# ---- 纯随机（验证 V1 == V2 和 不崩溃） ----

RANDOM = st.text(CHARS, max_size=200)


@given(RANDOM)
def test_find_artist_v2_no_crash(s):
    FindArtistV2(s)


@given(RANDOM)
def test_find_artist_v1_no_crash(s):
    FindArtist(s)


@given(RANDOM)
def test_v1_v2_agree(s):
    assert FindArtist(s) == FindArtistV2(s)


# ---- 结构化输入（验证返回正确的 artist） ----
@given(INPUT_AND_EXPECTED)
def test_find_artist_v2_correct(input_and_expected):
    s, expected = input_and_expected
    assert FindArtistV2(s) == expected


@given(INPUT_AND_EXPECTED)
def test_find_artist_v1_correct(input_and_expected):
    s, expected = input_and_expected
    assert FindArtist(s) == expected
