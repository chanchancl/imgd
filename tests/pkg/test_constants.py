from pkg.constants import (
    MATCH_EXACTLY,
    MATCH_FUZZY,
    MATCH_NO,
    MATCH_PART,
    match_result_to_text,
)


class TestMatchResultToText:
    def test_known_values(self):
        assert match_result_to_text(MATCH_NO) == "MATCH_NO"
        assert match_result_to_text(MATCH_FUZZY) == "MATCH_FUZZY"
        assert match_result_to_text(MATCH_PART) == "MATCH_PART"
        assert match_result_to_text(MATCH_EXACTLY) == "MATCH_EXACTLY"

    def test_unknown_value(self):
        assert match_result_to_text(999) == "ERROR"
