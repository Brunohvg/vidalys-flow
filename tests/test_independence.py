from scripts.check_independence import violations


def test_executable_code_is_independent():
    assert violations() == []
