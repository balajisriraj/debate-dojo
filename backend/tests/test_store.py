from unittest.mock import patch

from debatedojo.store import Store

SLOT = {"index": 0, "phase_id": "opening", "phase_name": "Opening", "exchange": 1}


def _session(store: Store, sid: str = "a" * 16, mode: str = "debate") -> str:
    store.create_session(
        id=sid,
        mode=mode,
        format_id="oxford",
        format={"id": "oxford"},
        topic="A motion",
        side="proposition",
        persona_id="debater",
        context="",
    )
    return sid


def test_turns_keep_order_timings_and_delivery(tmp_path):
    store = Store(tmp_path / "log.db")
    sid = _session(store)
    user = store.add_turn(
        sid,
        speaker="user",
        slot=SLOT,
        text="Hello",
        input="voice",
        duration_s=12.5,
        limit_s=60,
        timed_out=True,
        delivery={"wpm": 140},
    )
    reply = store.add_turn(sid, speaker="opponent", slot=SLOT, text="Hi", input="model")
    assert (user["idx"], reply["idx"]) == (0, 1)
    assert user["timed_out"] is True and user["delivery"] == {"wpm": 140} and user["limit_s"] == 60
    assert store.user_turn_count(sid) == 1
    # It is a real file: a fresh connection sees the same log.
    again = Store(tmp_path / "log.db").session(sid)
    assert [t["speaker"] for t in again["turns"]] == ["user", "opponent"]


def test_fact_check_flags_attach_to_their_turn(tmp_path):
    store = Store(":memory:")
    sid = _session(store)
    turn = store.add_turn(sid, speaker="user", slot=SLOT, text="Studies show 90%.", input="typed")
    flag = {"claim": "Studies show 90%", "verdict": "unsupported", "reason": "r", "evidence_needed": "e", "sources": []}
    store.add_fact_check(turn["id"], checked=2, method="knowledge", flags=[flag])
    saved = store.turn(turn["id"])
    assert saved["fact_check"] == {"checked": 2, "method": "knowledge"}
    assert saved["flags"][0]["claim"] == "Studies show 90%" and saved["flags"][0]["method"] == "knowledge"


def test_report_finishes_the_session_and_feeds_progress():
    store = Store(":memory:")
    first, second = _session(store, "a" * 16), _session(store, "b" * 16)
    _session(store, "c" * 16, mode="sales")
    for sid, score in ((first, 4), (second, 7)):
        card = {
            "overall": score * 10,
            "scores": [{"criterion": "argument", "score": score}, {"criterion": "evidence", "score": score - 1}],
        }
        store.save_report(sid, "debate", card, {"improvements": []})
    s = store.session(first)
    assert s["status"] == "finished" and s["overall"] == 40 and s["report"]["coaching"] == {"improvements": []}
    progress = store.progress("debate")
    assert [p["id"] for p in progress] == [first, second]
    assert progress[1]["scores"] == {"argument": 7, "evidence": 6}
    assert store.progress("sales") == []  # unfinished sessions do not count
    # Re-judging replaces the scores instead of duplicating them, and the bout keeps its place in the record.
    finished = store.session(first)["finished_at"]
    with patch("debatedojo.store.now", return_value="2999-01-01T00:00:00+00:00"):
        store.save_report(first, "debate", {"overall": 90, "scores": [{"criterion": "argument", "score": 9}]}, {})
    progress = store.progress("debate")
    assert [p["id"] for p in progress] == [first, second]
    assert progress[0]["scores"] == {"argument": 9} and progress[0]["finished_at"] == finished


def test_deleting_a_session_removes_its_log():
    store = Store(":memory:")
    sid = _session(store)
    turn = store.add_turn(sid, speaker="user", slot=SLOT, text="x", input="typed")
    store.add_fact_check(
        turn["id"],
        checked=1,
        method="knowledge",
        flags=[{"claim": "x", "verdict": "doubtful", "reason": "r", "evidence_needed": "e"}],
    )
    assert store.delete_session(sid)
    assert store.session(sid) is None and store.sessions() == []
    assert store.db.execute("SELECT COUNT(*) FROM flags").fetchone()[0] == 0
    assert not store.delete_session(sid)


def test_session_list_counts_user_turns():
    store = Store(":memory:")
    sid = _session(store)
    store.add_turn(sid, speaker="user", slot=SLOT, text="x", input="typed")
    store.add_turn(sid, speaker="opponent", slot=SLOT, text="y", input="model")
    [listed] = store.sessions()
    assert listed["user_turns"] == 1 and "format" not in listed
