from recsys.core import listen_weight, norm, split_artists


def test_finished_counts_fully():
    assert listen_weight(200, 240, "partial") == 1.0          # >= 80 % heard
    assert listen_weight(240, 240, "complete") == 1.0


def test_rejected_in_first_seconds_is_strongest_negative():
    assert listen_weight(5, 240, "skip") == -1.2
    assert listen_weight(9, 240, "skip") < listen_weight(30, 240, "skip") < 0


def test_share_heard_grades_the_listen():
    gave_a_chance = listen_weight(48, 240, "skip")             # 20 %
    most_of_it = listen_weight(144, 240, "partial")            # 60 %
    assert -0.6 < gave_a_chance < 0 < most_of_it < 1
    assert abs(most_of_it - 0.5) < 1e-9


def test_without_duration_falls_back_to_event():
    assert listen_weight(None, None, "complete") == 1.0
    assert listen_weight(None, None, "skip") == -1.0
    assert listen_weight(None, None, "whatever") == 0


def test_norm_strips_accents_and_punctuation():
    assert norm("Đen Vâu") == "den vau"
    assert norm("  Beyoncé!!  feat.  ") == "beyonce feat"


def test_split_artists():
    assert split_artists("A, B & C feat. D") == ["a", "b", "c", "d"]
    assert split_artists("Soap&Skin") == ["soap skin"]          # no spaces around & -> one artist
    assert split_artists("") == []
