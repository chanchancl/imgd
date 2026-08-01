# exact_candidates / fuzzy_candidates 依赖 cache_store 单例，跳过单测
from hypothesis import assume, given
from hypothesis import strategies as st

from pkg.matching import (
    _intersect_index,
    _ngram_index,
    _normalize_range_separators,
    _union_index,
    check_author_in_title,
    exactly_match,
    extract_number_from_string,
    extract_number_range_from_string,
    fuzz_match,
    part_match,
)

# ==== Property-based tests ====

CHARS = st.characters(blacklist_categories=("Cs",))
TEXT = st.text(CHARS)
TEXT_1 = st.text(CHARS, min_size=1)


# ---- _normalize_range_separators ----


@given(TEXT)
def test_nrs_idempotent(s):
    nrs = _normalize_range_separators
    assert nrs(nrs(s)) == nrs(s)


@given(TEXT)
def test_nrs_output_no_forbidden_chars(s):
    out = _normalize_range_separators(s)
    assert all(sep not in out for sep in "～〜－~")


# ---- exactly_match ----


@given(
    st.text(CHARS, min_size=1, max_size=100),
    st.text(CHARS, min_size=1, max_size=30),
    st.text(CHARS, max_size=30),
)
def test_exactly_match_substring(prefix, needle, suffix):
    assume(needle)
    assert exactly_match(prefix + needle + suffix, needle) is True


# ---- part_match ----


@given(TEXT, TEXT)
def test_part_match_result_in_cached(a, b):
    ok, sub = part_match(a, b)
    if ok:
        assert sub in a


# ---- fuzz_match ----


@given(st.lists(TEXT_1, min_size=1, max_size=10), TEXT_1)
def test_fuzz_match_exact(candidates, needle):
    candidates.append(needle)
    ok, matched = fuzz_match(candidates, needle, "")
    assert ok is True and matched == needle


# ---- _intersect_index / _union_index ----

from pkg.models import CacheSnapshot


def _make_snapshot(titles: list[str]) -> CacheSnapshot:
    return CacheSnapshot(
        titles=titles,
        trigram_index={},
        bigram_index={},
        authors=[],
        author_set=set(),
    )


# ---- NormalizeRangeSeparators ----


class TestNormalizeRangeSeparators:
    def test_fullwidth_tilde(self):
        assert _normalize_range_separators("1～3") == "1-3"

    def test_wave_dash(self):
        assert _normalize_range_separators("1〜3") == "1-3"

    def test_fullwidth_hyphen(self):
        assert _normalize_range_separators("1－3") == "1-3"

    def test_ascii_tilde(self):
        assert _normalize_range_separators("1~3") == "1-3"

    def test_unchanged(self):
        assert _normalize_range_separators("hello-world") == "hello-world"

    def test_mixed_separators(self):
        assert _normalize_range_separators("1～3 4〜5") == "1-3 4-5"


# ---- CheckAuthorInTitle ----


class TestCheckAuthorInTitle:
    def test_empty_author_always_ok(self):
        assert check_author_in_title("some title [artist]", "") is True

    def test_author_found(self):
        assert check_author_in_title("some title [artist]", "artist") is True

    def test_author_not_found(self):
        assert check_author_in_title("some title [artist]", "other") is False


# ---- ExtractNumberFromString ----


class TestExtractNumberFromString:
    def test_hash_number(self):
        assert extract_number_from_string("title #42") == 42

    def test_hash_takes_priority(self):
        assert extract_number_from_string("vol #7 99") == 7

    def test_last_token_number(self):
        assert extract_number_from_string("vol 3 extra") == 3

    def test_last_token_wins(self):
        assert extract_number_from_string("ch1 ch2") == 2

    def test_fallback_any_number(self):
        assert extract_number_from_string("abc123def") == 123

    def test_no_number(self):
        assert extract_number_from_string("no numbers here") is None

    def test_empty_string(self):
        assert extract_number_from_string("") is None


# ---- ExtractNumberRange ----


class TestExtractNumberRange:
    def test_simple_range(self):
        assert extract_number_range_from_string("1-3") == (1, 3)

    def test_tilde_range(self):
        assert extract_number_range_from_string("01~05") == (1, 5)
        assert extract_number_range_from_string("03~07") == (3, 7)

    def test_reversed_range_skipped(self):
        assert extract_number_range_from_string("5-3") is None

    def test_year_filtered(self):
        assert extract_number_range_from_string("2020-2023") is None

    def test_ordinal_filtered(self):
        assert extract_number_range_from_string("1st-3rd") is None

    def test_no_range(self):
        assert extract_number_range_from_string("just text") is None


# ---- ExactlyMatch ----


class TestExactlyMatch:
    def test_direct_substring(self):
        assert exactly_match("hello world", "world") is True

    def test_not_substring(self):
        assert exactly_match("hello", "xyz") is False

    def test_normalized_substring(self):
        assert exactly_match("vol 1～3", "1-3") is True

    def test_range_match(self):
        assert exactly_match("vol 1-3", "vol 2") is True

    def test_range_out_of_bounds(self):
        assert exactly_match("vol 1-3", "5") is False

    def test_empty_input(self):
        assert exactly_match("", "x") is False
        assert exactly_match("x", "") is False

    def test_range_with_prefix_mismatch(self):
        assert exactly_match("vol 1-3", "ch 2") is False


# ---- PartMatch ----


class TestPartMatch:
    def test_above_threshold(self):
        ok, sub = part_match("hello world", "hello")
        assert ok is True
        assert sub == "hello"

    def test_below_threshold(self):
        ok, _ = part_match("abcdefghij", "xyz")
        assert ok is False

    def test_short_title_high_threshold(self):
        # len("xy")=2 < 10, threshold=0.85, ceil(2*0.85)=2, "xy" vs "abc" → 0
        ok, _ = part_match("abc", "xy")
        assert ok is False

    def test_empty(self):
        ok, sub = part_match("", "x")
        assert ok is False
        assert sub == ""


# ---- FuzzMatch ----


class TestFuzzMatch:
    def test_exact_fuzzy_match(self):
        titles = ["abcdefg", "hijklmn"]
        ok, matched = fuzz_match(titles, "abcdefg", "")
        assert ok is True
        assert matched == "abcdefg"

    def test_no_match(self):
        titles = ["aaaa", "bbbb"]
        ok, _ = fuzz_match(titles, "zzzz", "")
        assert ok is False

    def test_author_skip_wrong(self):
        # "abcdef" ratio vs "abcdef_x" = 0.857 > 0.8, author "y" skips first match
        titles = ["abcdef_x", "abcdef_y"]
        ok, matched = fuzz_match(titles, "abcdef", "y")
        assert ok is True
        assert matched == "abcdef_y"


# ---- NgramIndex ----


class TestNgramIndex:
    def test_trigram_index_selected(self):
        snap = _make_snapshot(["abcde"])
        result = _ngram_index(snap, "hello")
        assert result is snap.trigram_index

    def test_bigram_index_selected(self):
        snap = _make_snapshot(["ab"])
        result = _ngram_index(snap, "hi")
        assert result is snap.bigram_index

    def test_none_for_one_char(self):
        snap = _make_snapshot(["a"])
        assert _ngram_index(snap, "x") is None


# ---- IntersectIndex ----


class TestIntersectIndex:
    def test_intersection(self):
        idx = {"a": frozenset({0, 1}), "b": frozenset({0, 2})}
        assert _intersect_index(idx, {"a", "b"}) == frozenset({0})

    def test_missing_gram(self):
        idx = {"a": frozenset({0, 1})}
        assert _intersect_index(idx, {"a", "x"}) == frozenset()

    def test_single_gram(self):
        idx = {"a": frozenset({0, 1, 2})}
        assert _intersect_index(idx, {"a"}) == frozenset({0, 1, 2})


# ---- UnionIndex ----


class TestUnionIndex:
    def test_union(self):
        idx = {"a": frozenset({0}), "b": frozenset({1, 2}), "f": frozenset({7, 8, 9})}
        assert _union_index(idx, {"a", "b"}, 100) == frozenset({0, 1, 2})

    def test_exceeds_max(self):
        idx = {"a": frozenset({0, 1, 2})}
        assert _union_index(idx, {"a"}, 2) == None

    def test_all_missing(self):
        idx = {"x": frozenset({0})}
        assert _union_index(idx, {"y", "z"}, 10) == frozenset()

    def test_single_gram(self):
        idx = {"a": frozenset({0, 1})}
        assert _union_index(idx, {"a"}, 10) == frozenset({0, 1})
