"""A system spans several bars, not one, and the OCR misreads now and then.
The continuity check exists to detect MISSING CONTENT, not to react to every
failed reading."""
from tabextract.verify import analyze_measure_sequence


def test_multi_measure_systems_are_not_jumps():
    """Seven bars per system is a healthy progression, not a gap."""
    result = analyze_measure_sequence([1, 8, 15, 22, 29, 36])

    assert result.issues == []
    assert "no gaps" in result.summary


def test_gap_left_by_an_unreadable_system_is_not_a_jump():
    """If the middle one could not be read, the jump between the two legible
    ones is naturally twice as large: that is not missing content."""
    result = analyze_measure_sequence([1, 8, None, 22, 29])

    assert result.issues == []


def test_isolated_misread_is_ignored_and_does_not_poison_the_next_comparison():
    """A 113 read as 13: the sequence recovers on its own at the next one."""
    result = analyze_measure_sequence([99, 106, 13, 119, 125, 130])

    assert result.issues == [], f"should report nothing, reported: {result.summary}"
    assert "13" not in result.summary.split("bars ")[1].split("-")[0]


def test_bad_first_reading_does_not_poison_the_whole_song():
    """The first reading is validated against nothing; when it goes wrong (a 4
    read as 441) it used to drag the whole song with it."""
    result = analyze_measure_sequence([441, 5, 10, 16, 22, 27, 34])

    assert result.issues == []
    assert result.summary.startswith("bars 5-34")


def test_a_real_missing_chunk_is_still_reported():
    """Control: what the check exists to catch has to keep firing."""
    result = analyze_measure_sequence([1, 8, 15, 22, 190, 197, 204, 211])

    assert result.issues, "a genuinely lost page has to be reported"
    assert result.issues[0].kind == "gap"


def test_low_read_rate_reports_unreliable_instead_of_false_jumps():
    numbers = [75, None, None, None, 40, None, None, None, 92, None, None, 16]

    result = analyze_measure_sequence(numbers)

    assert result.issues == [], "without reliable signal, gaps are not invented"
    assert "unreliable OCR" in result.summary
    assert "no bar number could be read" not in result.summary
