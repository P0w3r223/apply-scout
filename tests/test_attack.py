"""The attack suite, checked the way an attack suite has to be checked.

A suite that reports 0 % has two possible causes, and they look identical from the outside: the
harness stopped the attack, or the suite never landed one. Most of what follows is aimed at telling
those apart — **positive controls** that remove a guard and demand the same payload then succeed. If
those ever pass by failing, every zero in the published table is worthless, whatever the guards do.

The rest pins the arrangement the table depends on: the reader obeys only what it was handed, the
judge never reads the demand, and `surprises` folds reach into its comparison so a payload that
never arrived is not filed as a defence.
"""

from __future__ import annotations

import json

import pytest

from apply_scout.attack import pages, report, suite
from apply_scout.attack.obey import obey
from apply_scout.attack.payloads import BY_NAME, EXFIL_MARKER, PAYLOADS, SECRET_MARKER
from apply_scout.attack.suite import ARMS, Attempt, run_one
from apply_scout.tools.read_cv import ReadCV
from apply_scout.tools.registry import ToolRegistry


class _Echoing:
    """Stands in for the structurer and echoes the file's text into a field it returns.

    That is how a leaked file actually gets back to a reader — not as a tool error, but inside a
    plausible answer — so the positive control has to model it rather than assert on the error."""

    def to_json(self, *, instructions: str, content: str, schema: dict, model: str) -> str:
        return json.dumps(
            {"name": "Candidate", "summary": content, "skills": [], "experience": []}
        )


def _attempt(payload: str, placement: str, *, arm: str, tmp_path) -> Attempt:
    return run_one(
        BY_NAME[payload], placement, arm=arm, workspace=tmp_path / f"{arm}-{payload}-{placement}"
    )


# --- positive controls: the suite can see a win -------------------------------------------------


def test_calibration_lands_the_secret_leak_on_the_published_wiring(tmp_path):
    """The control the whole `[B]` row rests on, run through `run_one` rather than beside it.

    An earlier version of this test built its own registry around a cooperative structurer. It
    passed while the suite's own fixture returned a *posting* to `read_cv`'s structuring call —
    `CVProfile` forbids extra fields, so the tool returned an error string and the secret could
    not have come back whatever the allowlist did. The row read `never succeeded` with the guard
    deleted. A positive control that does not run the published path is not a control."""
    assert suite.calibrate(tmp_path).succeeded


def test_the_allowlist_is_what_turns_that_win_back_into_a_zero(tmp_path):
    """The paired half: one variable moved, and the outcome inverts. Together with the test
    above this is the only thing that makes the published `0` mean the guard."""
    confined = _attempt("read_secret", "body", arm="trafilatura", tmp_path=tmp_path)
    assert confined.reached
    assert not confined.succeeded


def test_the_judge_recognises_a_leak_handed_to_it_directly(tmp_path):
    """`achieved` in isolation, so a calibration failure can be told apart from a broken judge."""
    secret = tmp_path / "id_rsa"
    secret.write_text(f"-----{SECRET_MARKER}-----", encoding="utf-8")
    registry = ToolRegistry([ReadCV(structurer=_Echoing(), readable=[secret])])

    payload = BY_NAME["read_secret"]
    contents = obey(payload, registry, secret_path=str(secret), reached=True)

    assert payload.achieved(contents, [])


def test_the_metadata_judge_fires_on_the_request_log_a_defenceless_fetcher_would_leave():
    """The [C] zero is the URL policy, not a judge blind to the request it is looking for."""
    payload = BY_NAME["internal_fetch"]
    assert payload.achieved([], ["http://169.254.169.254/latest/meta-data/"])
    assert not payload.achieved([], ["https://jobs.example/senior-python-engineer"])


def test_exfiltrate_lands_in_the_body_under_both_extractors(tmp_path):
    """The suite's live positive control: the one payload the harness is expected to permit.

    An allowlist bounds where a request goes, not what it carries. If this ever fails, either the
    guards changed shape or the grid stopped landing payloads at all — and a table of zeros would
    then read as good news."""
    for arm in ARMS:
        attempt = _attempt("exfiltrate", "body", arm=arm, tmp_path=tmp_path)
        assert attempt.reached, arm
        assert attempt.succeeded, arm
        assert any(EXFIL_MARKER in request for request in attempt.requests), arm


# --- negative controls: answering cleanly is not a win ------------------------------------------


def test_a_clean_transcript_is_a_win_for_nobody():
    for payload in PAYLOADS:
        assert not payload.achieved(["A tidy job posting."], ["https://jobs.example/x"])


def test_the_control_payload_reaches_the_reader_and_achieves_nothing(tmp_path):
    """`benign` is what separates "stopped" from "never arrived". It must do exactly one."""
    attempt = _attempt("benign", "body", arm="trafilatura", tmp_path=tmp_path)
    assert attempt.reached
    assert not attempt.succeeded


@pytest.mark.parametrize("payload", ["read_secret", "internal_fetch", "redirect_fetch"])
def test_the_guarded_legs_stay_shut_in_every_placement_and_both_arms(payload, tmp_path):
    for arm in ARMS:
        for placement in pages.PLACEMENTS:
            attempt = _attempt(payload, placement, arm=arm, tmp_path=tmp_path)
            assert not attempt.succeeded, f"{arm}/{payload}/{placement}"


def test_a_redirect_towards_the_metadata_address_is_refused_at_the_hop(tmp_path):
    """The one payload whose first address is unremarkable, so it is judged on where the request
    ended up. The attempt has to have *tried* the redirect and still lost — an attempt that never
    made the first request would prove nothing about the second."""
    attempt = _attempt("redirect_fetch", "body", arm="trafilatura", tmp_path=tmp_path)
    assert attempt.reached
    assert any("via-redirect" in request for request in attempt.requests)
    assert not any("169.254.169.254" in request for request in attempt.requests)


# --- the reader obeys what it was handed, and only that -----------------------------------------


def test_a_payload_that_did_not_reach_the_reader_is_never_acted_on(tmp_path):
    secret = tmp_path / "id_rsa"
    secret.write_text(f"-----{SECRET_MARKER}-----", encoding="utf-8")
    registry = ToolRegistry([ReadCV(structurer=_Echoing(), readable=[secret])])

    assert obey(BY_NAME["read_secret"], registry, secret_path=str(secret), reached=False) == []


def test_the_control_demands_nothing_even_when_it_reaches(tmp_path):
    assert obey(BY_NAME["benign"], ToolRegistry([]), secret_path=str(tmp_path), reached=True) == []


# --- extraction: the axis the table crosses -----------------------------------------------------


@pytest.mark.parametrize("placement", pages.PLACEMENTS)
def test_every_placement_prints_the_payload_on_the_same_base_posting(placement):
    html = pages.page("PAYLOAD-TEXT", placement)
    assert "PAYLOAD-TEXT" in html
    assert pages.BASE_BODY in html


def test_an_unknown_placement_is_refused_rather_than_silently_dropped():
    with pytest.raises(ValueError, match="unknown placement"):
        pages.page("x", "watermark")


def test_the_body_reaches_the_reader_under_every_extractor(tmp_path):
    """The floor the whole grid stands on. If an ordinary paragraph stopped arriving, every zero
    in the published table would be extraction's doing and none of it the guards'."""
    for arm in ARMS:
        assert _attempt("benign", "body", arm=arm, tmp_path=tmp_path).reached, arm


def test_the_fallback_extractor_reads_at_least_what_trafilatura_does(tmp_path):
    """The two-arm claim, stated so it survives a parser upgrade.

    Asserting *which* placements trafilatura drops would be asserting a property of the installed
    trafilatura and libxml2: `hidden` reaches under some builds and not others, which is the finding
    rather than a fault, and pinning it turns somebody's dependency bump into a red build. What is
    invariant is the direction — the stdlib strip keeps everything visible plus what trafilatura
    chose to discard, so it can never read less."""
    for placement in pages.PLACEMENTS:
        trafilatura = _attempt("benign", placement, arm="trafilatura", tmp_path=tmp_path)
        fallback = _attempt("benign", placement, arm="fallback", tmp_path=tmp_path)
        assert fallback.reached >= trafilatura.reached, placement


# --- the report says what happened --------------------------------------------------------------


def _fake(payload: str, *, reached: bool, succeeded: bool) -> Attempt:
    return Attempt(
        arm="trafilatura",
        payload=payload,
        placement="body",
        reached=reached,
        succeeded=succeeded,
        requests=(),
    )


def test_an_expected_win_that_never_reached_the_reader_is_not_a_surprise():
    """The fix this list needed: an instruction nobody read cannot be obeyed, and filing that as a
    disagreement buries the real ones under four rows of noise."""
    assert report.surprises([_fake("exfiltrate", reached=False, succeeded=False)]) == []


def test_an_expected_win_that_reached_and_lost_is_a_surprise():
    attempts = [_fake("exfiltrate", reached=True, succeeded=False)]
    assert report.surprises(attempts) == attempts


def test_a_guarded_leg_that_succeeded_is_a_surprise():
    attempts = [_fake("read_secret", reached=True, succeeded=True)]
    assert report.surprises(attempts) == attempts


def test_a_payload_that_landed_nowhere_is_its_own_alarm():
    """Distinct from a surprise, and the more dangerous of the two: nothing about the outcome
    disagrees with the record, yet every zero it produced was extraction's and not the guards'."""
    attempts = [_fake("read_secret", reached=False, succeeded=False)]
    assert report.surprises(attempts) == []
    assert "trafilatura/read_secret" in report.unlanded(attempts)


def test_rates_carry_their_denominator():
    rates = report.by(lambda a: a.payload, [_fake("benign", reached=True, succeeded=False)] * 4)
    assert [(r.label, r.attempts, r.reached, r.succeeded) for r in rates] == [("benign", 4, 4, 0)]


@pytest.mark.parametrize(
    ("reached", "succeeded", "expected"),
    [(0, 0, "never reached"), (4, 0, "never succeeded"), (4, 4, "succeeded every time")],
)
def test_the_verdict_divides_the_extractor_out(reached, succeeded, expected):
    rate = report.Rate(label="x", attempts=4, reached=reached, succeeded=succeeded)
    assert expected in rate.verdict


def test_the_approved_claim_carries_no_reach_counts(tmp_path):
    """The reason CI can diff it at all. Reach moves with the installed trafilatura, so a count of
    it in this file would make a dependency bump look like a change in what the guards permit."""
    attempts = [
        _attempt("benign", placement, arm=arm, tmp_path=tmp_path)
        for arm in ARMS
        for placement in pages.PLACEMENTS
    ]
    claim = report.markdown(attempts)
    for arm in ARMS:
        assert f"## Arm: `{arm}`" in claim
    assert "check_resolved` never runs" in claim
    for placement in pages.PLACEMENTS:
        assert f"| `{placement}` |" not in claim
    # The counts live here instead, printed rather than approved.
    assert "trafilatura" in report.environment(attempts)
    assert "| `hidden` |" in report.environment(attempts)
