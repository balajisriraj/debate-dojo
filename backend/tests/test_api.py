import json

import pytest
from fastapi.testclient import TestClient

from debatedojo.api import create_app


@pytest.fixture
def client(settings, service):
    with TestClient(create_app(settings, service)) as c:
        yield c


def _events(body: str) -> list[dict]:
    return [json.loads(line[5:]) for line in body.splitlines() if line.startswith("data:")]


def _start(client, **kw) -> dict:
    body = {"mode": "debate", "topic": "This house would ban smartphones in schools", "format_id": "rapid-fire", **kw}
    res = client.post("/api/sessions", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def test_health_and_catalog(client):
    health = client.get("/api/health").json()
    assert health["status"] == "ok" and health["llm"] == "scripted" and health["fact_check"] == "knowledge"
    modes = {m["id"]: m for m in client.get("/api/catalog").json()["modes"]}
    assert set(modes) == {"debate", "meeting", "sales"}
    assert {f["id"] for f in modes["debate"]["formats"]} >= {"oxford", "lincoln-douglas", "rapid-fire"}
    assert modes["sales"]["samples"][0]["product"]


def test_start_a_session_with_custom_timers(client):
    s = _start(client, side="opposition", timers={"rapid": 45})
    assert s["side"] == "opposition" and s["status"] == "live"
    assert [slot["seconds"] for slot in s["plan"]] == [45] * 5
    assert s["position"]["slot"]["index"] == 0 and len(s["rubric"]) == 5
    assert client.get(f"/api/sessions/{s['id']}").json()["id"] == s["id"]


@pytest.mark.parametrize(
    "body",
    [
        {"mode": "chess", "topic": "Something"},
        {"mode": "debate", "topic": "x"},
        {"mode": "debate", "topic": "A motion here", "format_id": "sales"},
        {"mode": "sales", "topic": "A product", "persona_id": "finance-director"},
        {"mode": "debate", "topic": "A motion here", "timers": {"nope": 30}},
    ],
)
def test_bad_sessions_are_rejected(client, body):
    assert client.post("/api/sessions", json=body).status_code == 422


def test_a_turn_streams_server_sent_events(client):
    s = _start(client)
    res = client.post(
        f"/api/sessions/{s['id']}/turns",
        json={
            "text": "Phones never help anyone learn.",
            "input": "voice",
            "duration_s": 12,
            "talk_seconds": 7.5,
            "longest_pause_s": 1.5,
        },
    )
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/event-stream")
    events = _events(res.text)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "step" and kinds[-1] == "final"
    assert {"turn", "flags", "token", "reply", "position"} <= set(kinds)
    turn = next(e for e in events if e["type"] == "turn")["turn"]
    assert turn["input"] == "voice" and turn["delivery"]["wpm"] == 40.0 and turn["delivery"]["longest_pause_s"] == 1.5


def test_full_session_then_progress_then_delete(client):
    s = _start(client)
    for n in range(5):
        res = client.post(
            f"/api/sessions/{s['id']}/turns",
            json={"text": f"Point {n}: phones distract pupils, because attention is limited."},
        )
        assert res.status_code == 200
    kinds = [e["type"] for e in _events(res.text)]
    assert "scorecard" in kinds and "coaching" in kinds
    assert client.post(f"/api/sessions/{s['id']}/turns", json={"text": "late"}).status_code == 409
    assert client.post(f"/api/sessions/{s['id']}/finish").status_code == 409
    progress = client.get("/api/progress/debate").json()
    assert [p["id"] for p in progress["sessions"]] == [s["id"]]
    assert set(progress["sessions"][0]["scores"]) == {c["id"] for c in progress["rubric"]}
    assert client.get("/api/sessions").json()[0]["status"] == "finished"
    assert client.delete(f"/api/sessions/{s['id']}").json() == {"deleted": s["id"]}
    assert client.get(f"/api/sessions/{s['id']}").status_code == 404


def test_finish_early_streams_the_report(client):
    s = _start(client, mode="meeting", topic="Replace the weekly status meeting with written updates", format_id=None)
    assert client.post(f"/api/sessions/{s['id']}/finish").status_code == 409
    client.post(f"/api/sessions/{s['id']}/turns", json={"text": "I propose written updates, starting next week."})
    events = _events(client.post(f"/api/sessions/{s['id']}/finish").text)
    assert [e["type"] for e in events if e["type"] in ("scorecard", "coaching", "final")] == [
        "scorecard",
        "coaching",
        "final",
    ]


def test_input_validation(client):
    s = _start(client)
    assert client.post(f"/api/sessions/{s['id']}/turns", json={"text": "   "}).status_code == 422
    assert client.post(f"/api/sessions/{s['id']}/turns", json={"text": "", "timed_out": True}).status_code == 200
    assert client.post(f"/api/sessions/{s['id']}/turns", json={"text": "x", "input": "telepathy"}).status_code == 422
    assert client.get("/api/sessions/not-an-id").status_code == 400
    assert client.get("/api/sessions/0123456789abcdef").status_code == 404
    assert client.post("/api/sessions/0123456789abcdef/turns", json={"text": "hi"}).status_code == 404
    assert client.get("/api/progress/chess").status_code == 404
