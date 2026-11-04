import pytest

from debatedojo.config import Settings
from debatedojo.formats import MAX_SECONDS, MIN_SECONDS, load_catalog, overtime, plan, position


@pytest.fixture
def catalog():
    s = Settings(llm="scripted")
    return load_catalog(s.formats_dir, s.personas_path)


def test_every_mode_has_formats_and_personas(catalog):
    assert {f.id for f in catalog.formats_for("debate")} >= {"oxford", "lincoln-douglas", "rapid-fire"}
    assert [f.id for f in catalog.formats_for("meeting")] == ["meeting"]
    assert [f.id for f in catalog.formats_for("sales")] == ["sales"]
    assert {"finance-director", "engineering-lead"} <= set(catalog.personas["meeting"])
    for persona in catalog.personas["sales"].values():
        assert set(persona.objections) == {"price", "timing", "incumbent", "authority"}


def test_debate_formats_have_the_promised_phases(catalog):
    assert [p.name for p in catalog.format("oxford").phases] == ["Opening", "Rebuttal", "Closing"]
    ld = catalog.format("lincoln-douglas")
    assert [p.id for p in ld.phases] == ["constructive", "cross-examination", "rebuttal"]
    assert ld.phases[1].exchanges == 3 and ld.phases[1].opponent == "answer"
    rapid = catalog.format("rapid-fire")
    assert len(plan(rapid)) == 5 and all(s.seconds == 30 for s in plan(rapid))


def test_plan_walks_phases_and_exchanges_in_order(catalog):
    slots = plan(catalog.format("sales"))
    assert [(s.phase_id, s.exchange) for s in slots] == [
        ("opening", 1),
        ("objections", 1),
        ("objections", 2),
        ("objections", 3),
        ("objections", 4),
        ("close", 1),
    ]
    assert [s.index for s in slots] == list(range(6))


def test_position_follows_the_number_of_turns(catalog):
    fmt = catalog.format("oxford")
    assert position(fmt, 0).slot.phase_id == "opening"
    assert position(fmt, 2).slot.phase_id == "closing"
    done = position(fmt, 3)
    assert done.done and done.slot is None and done.turn == done.total == 3
    assert position(fmt, 9).done
    with pytest.raises(ValueError):
        position(fmt, -1)


def test_user_timers_apply_and_clamp(catalog):
    fmt = catalog.format("oxford").with_timers({"opening": 240, "closing": 5, "rebuttal": 10_000})
    assert [p.seconds for p in fmt.phases] == [240, MAX_SECONDS, MIN_SECONDS]
    assert catalog.format("oxford").phases[0].seconds == 180  # the original is untouched
    with pytest.raises(ValueError, match="Unknown phase"):
        catalog.format("oxford").with_timers({"cross-examination": 60})


def test_overtime_allows_a_small_grace():
    assert not overtime(60, 61.5)
    assert overtime(60, 62.5)
    assert overtime(30, 40, grace_s=0)


def test_unknown_format_and_persona_raise(catalog):
    with pytest.raises(KeyError):
        catalog.format("british-parliamentary")
    with pytest.raises(KeyError):
        catalog.persona("sales", "finance-director")
    assert catalog.persona("debate", None).id == "debater"
