"""Tests for trailer-quote mining and dialogue-driven editing."""

from trailer_agent.quotes import mine_quotes, score_line
from trailer_agent.transcript import SpeechSegment


def seg(start, end, text):
    return SpeechSegment(start=start, end=end, text=text)


def test_punchy_lines_beat_rambling():
    punchy = score_line("We're out of time!")
    rambling = score_line(
        "So, um, like I was saying earlier, you know, we should probably think "
        "about maybe getting this whole thing organized at some point soon."
    )
    assert punchy > rambling


def test_power_words_raise_score():
    assert score_line("Nothing will ever be the same.") > score_line("The soup is warm.")


def test_questions_and_exclamations_score_high():
    assert score_line("Are you ready?") > score_line("I am ready")


def test_empty_line_scores_zero():
    assert score_line("") == 0.0
    assert score_line("   ") == 0.0


def test_mine_quotes_picks_best_and_spreads():
    segments = [
        seg(10.0, 12.0, "We're out of time!"),
        seg(11.0, 13.0, "Nothing will ever be the same."),   # too close to the first
        seg(100.0, 102.0, "Are you ready to fight?"),
        seg(200.0, 203.0, "Um, so, yeah, whatever, you know."),
        seg(300.0, 302.0, "This is where it ends."),
    ]
    quotes = mine_quotes(segments, 3, min_gap=20.0)
    texts = [q.text for q in quotes]
    assert len(quotes) == 3
    assert "Um, so, yeah, whatever, you know." not in texts
    # the two overlapping early lines can't both appear
    assert not ("We're out of time!" in texts
                and "Nothing will ever be the same." in texts)


def test_mine_quotes_rejects_marathon_segments():
    segments = [seg(10.0, 30.0, "A twenty second monologue that no trailer would use!")]
    assert mine_quotes(segments, 3) == []


def test_editor_builds_around_quotes():
    from tests.test_brain import fake_analysis, opts
    from trailer_agent.editor import plan_professional

    analysis = fake_analysis()
    analysis.segments = [
        seg(50.0, 52.0, "Nothing will ever be the same!"),
        seg(150.0, 152.0, "Are you ready to fight?"),
        seg(400.0, 402.0, "This is where everything ends."),
    ]
    plan = plan_professional(analysis, opts())
    notes = [i.note for i in plan.timeline]
    assert any(n.startswith("the line") for n in notes), notes
    assert any(n.startswith("setup") and "“" in n for n in notes), notes
    # "the line" sits right before the breath/title block
    line_idx = next(i for i, n in enumerate(notes) if n.startswith("the line"))
    assert any(n == "breath" or n == "title" for n in notes[line_idx + 1:])


def test_editor_fills_toward_target():
    from tests.test_brain import fake_analysis, opts
    from trailer_agent.editor import plan_professional

    plan = plan_professional(fake_analysis(duration=1200.0, n_scenes=60),
                             opts(target_duration=60.0))
    assert plan.total_duration() >= 60.0 * 0.85
