import os
import threading
import time
import uuid

import pytest

import single_instance


def _name():
    # A private mutex per test, so a running copy of the app cannot interfere.
    return "Local\\AccessibleIPTVClient-test-" + uuid.uuid4().hex


def test_second_copy_is_refused_while_the_first_holds_the_guard(tmp_path):
    name = _name()
    first = single_instance.acquire(str(tmp_path), name)
    assert first is not None
    try:
        assert single_instance.acquire(str(tmp_path), name) is None
    finally:
        first.release()
    again = single_instance.acquire(str(tmp_path), name)
    assert again is not None, "the guard must be free once the first copy lets go"
    again.release()


def test_hand_over_reports_shown_once_the_running_copy_takes_the_request(tmp_path):
    name = _name()
    first = single_instance.acquire(str(tmp_path), name)
    try:
        def running_copy():
            # The running copy's timer, compressed.
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if single_instance.take_show_request(str(tmp_path)):
                    return
                time.sleep(0.05)

        watcher = threading.Thread(target=running_copy)
        watcher.start()
        assert single_instance.hand_over(str(tmp_path), timeout=5, poll=0.05, name=name) == "shown"
        watcher.join()
    finally:
        first.release()


def test_hand_over_runs_after_all_when_the_other_copy_exits(tmp_path):
    """A copy that was closing must not leave the user with nothing running."""
    name = _name()
    first = single_instance.acquire(str(tmp_path), name)
    threading.Timer(0.3, first.release).start()
    outcome = single_instance.hand_over(str(tmp_path), timeout=5, poll=0.05, name=name)
    assert isinstance(outcome, single_instance.InstanceGuard)
    assert not os.path.exists(tmp_path / single_instance.SHOW_REQUEST_FILE)
    outcome.release()


def test_hand_over_gives_up_on_a_copy_that_never_answers(tmp_path):
    name = _name()
    first = single_instance.acquire(str(tmp_path), name)
    try:
        assert single_instance.hand_over(str(tmp_path), timeout=0.4, poll=0.05,
                                         name=name) == "unresponsive"
        assert not os.path.exists(tmp_path / single_instance.SHOW_REQUEST_FILE)
    finally:
        first.release()


def test_no_request_means_nothing_to_show(tmp_path):
    assert single_instance.take_show_request(str(tmp_path)) is False


@pytest.mark.skipif(os.name != "nt", reason="Windows update helper")
def test_update_helper_accepts_a_restart_that_handed_over():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "update_helper.ps1"), encoding="ascii") as handle:
        helper = handle.read()
    assert "$app.ExitCode -eq {code}".format(code=single_instance.HANDED_OVER_EXIT_CODE) in helper


def test_main_hands_over_before_building_a_second_window():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "main.py"), encoding="utf-8") as handle:
        source = handle.read()
    entry = source[source.index('if __name__ == "__main__":'):]
    assert entry.index("single_instance.acquire(") < entry.index("IPTVClient()")
    assert "watch_for_show_requests(" in entry
