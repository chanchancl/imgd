from pkg.cache import _build_ngram_index, _extract_ngrams


class TestExtractNgrams:
    def test_trigram(self):
        assert _extract_ngrams("abcd", 3) == {"abc", "bcd"}

    def test_bigram(self):
        assert _extract_ngrams("abc", 2) == {"ab", "bc"}

    def test_insufficient_length(self):
        assert _extract_ngrams("ab", 3) == set()

    def test_exact_length(self):
        assert _extract_ngrams("abc", 3) == {"abc"}

    def test_empty_string(self):
        assert _extract_ngrams("", 3) == set()


class TestBuildNgramIndex:
    def test_trigram_index(self):
        titles = ["abcde", "bcdef"]
        idx = _build_ngram_index(titles, n=3)
        # "abcde" grams: abc, bcd, cde  → indices 0
        # "bcdef" grams: bcd, cde, def  → indices 1
        assert idx["abc"] == frozenset({0})
        assert idx["bcd"] == frozenset({0, 1})
        assert idx["def"] == frozenset({1})

    def test_empty_titles(self):
        assert _build_ngram_index([], 3) == {}

    def test_short_title_skipped(self):
        titles = ["ab", "abcd"]
        idx = _build_ngram_index(titles, n=3)
        # "ab" has no trigram, should be skipped
        assert "ab" not in idx
