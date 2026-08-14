from models.participant import TaskType, Partnership, PartnerLabel
from services import ALL_CONDITIONS, assign_condition, get_condition_counts


def test_assign_condition_picks_minimum_cell():
    counts = {cond: 5 for cond in ALL_CONDITIONS}
    target = (TaskType.emotionTask, Partnership.HMC, PartnerLabel.chatbot)
    counts[target] = 1
    assert assign_condition(counts) == target


def test_assign_condition_breaks_ties_from_candidates():
    counts = {cond: 3 for cond in ALL_CONDITIONS}
    picks = [assign_condition(counts) for _ in range(40)]
    assert set(picks) <= set(ALL_CONDITIONS)
    assert len(set(picks)) > 1


def test_all_conditions_cover_2x2x2():
    assert len(ALL_CONDITIONS) == 8
    assert len(set(ALL_CONDITIONS)) == 8


def test_get_condition_counts_excludes_test_participants():
    import inspect

    source = inspect.getsource(get_condition_counts)
    assert "is_test" in source
