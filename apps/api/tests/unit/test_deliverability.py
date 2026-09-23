import pytest

from gtmos.domain.deliverability import (
    DEFAULT_RAMP,
    DOES_NOT_MODEL,
    PROVIDER_DAILY_CAP,
    REPUTATION_SAFE_DAILY_CAP,
    THRESHOLDS,
    ObservedSignals,
    RampSchedule,
    assess_risk,
    assess_signal,
    campaign_feasibility,
    days_to_send,
    sending_capacity,
)

# A programme with nothing wrong with it: 4,000 sends, 40 bounces (1%), no complaints, 2 unsubscribes,
# a 4% reply rate and a clean list. Every rate sits inside its threshold.
CLEAN = ObservedSignals(
    sent=4_000,
    bounced=40,
    replies=160,
    accounts_touched=1_000,
    spam_complaints=0,
    unsubscribes=2,
    contacts_with_email=5_000,
    unsendable_addresses=25,
    unverified_addresses=200,
)


def test_a_new_mailbox_cannot_send_at_its_configured_cap_on_day_one():
    day_one = sending_capacity(mailboxes=4, per_mailbox_daily_cap=40, warmup_day=1)
    assert day_one.per_mailbox_allowance == DEFAULT_RAMP.start_per_day
    assert day_one.daily_capacity == 4 * DEFAULT_RAMP.start_per_day
    assert day_one.is_warming and day_one.limiting_factor == "warmup"
    mature = sending_capacity(mailboxes=4, per_mailbox_daily_cap=40, warmup_day=DEFAULT_RAMP.days_to_full_volume(40))
    assert mature.daily_capacity == 160 and not mature.is_warming
    assert mature.limiting_factor == "configured_cap"
    # A higher cap is not free: the ramp takes longer to earn it, so warmup lasts longer.
    assert DEFAULT_RAMP.days_to_full_volume(200) > DEFAULT_RAMP.days_to_full_volume(40)


def test_volume_comes_from_more_mailboxes_not_from_a_higher_cap():
    ten_boxes = sending_capacity(mailboxes=10, per_mailbox_daily_cap=40, warmup_day=90).daily_capacity
    one_big_box = sending_capacity(mailboxes=1, per_mailbox_daily_cap=400, warmup_day=90).daily_capacity
    # Both arithmetic to 400/day, and the model says so — but the second one says it is over the
    # reputation-safe rule of thumb, which is the whole difference between the two plans.
    assert ten_boxes == one_big_box == 400
    assert str(REPUTATION_SAFE_DAILY_CAP) in sending_capacity(1, 400, 90).note
    # The provider's own published ceiling still clamps a nonsense cap.
    assert sending_capacity(1, 10_000, 90).per_mailbox_daily_cap == PROVIDER_DAILY_CAP


def test_days_to_work_a_list_multiplies_by_the_sequence_length():
    one_touch = campaign_feasibility(list_size=1_000, steps_per_account=1, mailboxes=4, warmup_day=90)
    four_touch = campaign_feasibility(list_size=1_000, steps_per_account=4, mailboxes=4, warmup_day=90)
    assert one_touch.total_sends == 1_000 and four_touch.total_sends == 4_000
    assert (one_touch.days_to_work_list, four_touch.days_to_work_list) == (7, 25)  # 1,000 and 4,000 at 160/day
    # The first touch to every account lands long before the sequence finishes; both numbers are reported
    # because campaigns are planned against the first and judged against the second.
    assert four_touch.days_to_first_touch == one_touch.days_to_work_list


def test_warmup_is_simulated_day_by_day_rather_than_divided_by_todays_capacity():
    warming = days_to_send(2_000, mailboxes=4, per_mailbox_daily_cap=40, warmup_day=1)
    mature = days_to_send(2_000, mailboxes=4, per_mailbox_daily_cap=40, warmup_day=90)
    assert mature == 13  # 2,000 / 160 a day, rounded up
    # Dividing by day-one capacity (20/day) would predict 100 days; dividing by the steady state would
    # predict 13. The ramp makes the true answer sit between them.
    assert mature < warming < 100
    assert days_to_send(1_000, mailboxes=0) is None


def test_a_deadline_returns_the_mailbox_count_that_would_meet_it():
    plan = campaign_feasibility(list_size=4_000, steps_per_account=4, mailboxes=4, warmup_day=90, deadline_days=90)
    assert plan.verdict == "infeasible" and plan.fits_deadline is False
    assert plan.mailboxes_needed_for_deadline is not None
    bigger = campaign_feasibility(
        list_size=4_000,
        steps_per_account=4,
        mailboxes=plan.mailboxes_needed_for_deadline,
        warmup_day=90,
        deadline_days=90,
    )
    assert bigger.fits_deadline is True
    assert campaign_feasibility(0, 4, 4, warmup_day=90).verdict == "feasible"


def test_capacity_inputs_that_make_no_sense_raise_rather_than_returning_a_number():
    with pytest.raises(ValueError):
        sending_capacity(mailboxes=-1)
    with pytest.raises(ValueError):
        sending_capacity(mailboxes=4, warmup_day=0)
    with pytest.raises(ValueError):
        RampSchedule(start_per_day=5, daily_growth=1.0)
    with pytest.raises(ValueError):
        campaign_feasibility(list_size=-1, steps_per_account=3, mailboxes=4)


def test_thresholds_carry_the_published_number_and_the_source_it_came_from():
    spam = THRESHOLDS["spam_complaint"]
    assert (spam.warn, spam.severe) == (0.001, 0.003)  # Google: target 0.10%, hard limit 0.30%
    assert "google" in spam.source.lower()
    bounce = THRESHOLDS["bounce"]
    assert (bounce.warn, bounce.severe) == (0.02, 0.05)
    # Bounce and unsubscribe have no published limit anywhere, and the source string has to admit it.
    assert "rule of thumb" in bounce.source.lower()
    assert "no provider publishes" in THRESHOLDS["unsubscribe"].source.lower()


def test_one_complaint_in_a_small_sample_is_not_called_a_breach():
    tiny = assess_signal("spam_complaint", numerator=1, denominator=250, denominator_label="accounts touched")
    assert tiny.rate is not None and tiny.rate > THRESHOLDS["spam_complaint"].severe
    assert tiny.status == "watch" and not tiny.proven  # over the line, but the interval reaches back under it
    big = assess_signal("spam_complaint", numerator=40, denominator=5_000, denominator_label="accounts touched")
    assert big.status == "severe" and big.proven
    assert assess_signal("bounce", 0, 0, "messages sent").status == "no_data"


def test_list_quality_is_a_census_and_is_not_given_a_confidence_interval():
    census = assess_signal("unverified_share", 1_500, 10_000, "contacts with an email", is_sample=False)
    assert census.ci_low is None and census.ci_high is None
    assert "not a sample" in census.reason
    assert "interval" not in census.reason


def test_a_severe_bounce_rate_stops_the_plan_and_a_clean_one_clears_it_to_scale():
    severe = assess_risk(
        ObservedSignals(
            sent=4_000,
            bounced=400,  # 10%: a list nobody verified
            replies=40,
            accounts_touched=1_000,
            spam_complaints=0,
            unsubscribes=2,
            contacts_with_email=5_000,
            unsendable_addresses=25,
            unverified_addresses=200,
        )
    )
    assert severe.verdict == "stop" and severe.throttle_factor == 0.0
    assert any("verify the list" in a.lower() for a in severe.actions)

    clean = assess_risk(CLEAN)
    assert clean.verdict == "scale" and clean.throttle_factor == 1.0 and clean.risk_score == 0
    assert clean.coverage.startswith("All 6")


def test_a_proven_bounce_problem_halves_the_plan_even_while_it_is_under_the_severe_line():
    borderline = assess_risk(
        ObservedSignals(
            sent=10_000,
            bounced=300,  # 3.0%: over the 2% healthy line for the whole interval, under the 5% severe line
            replies=400,
            accounts_touched=2_500,
            spam_complaints=0,
            unsubscribes=5,
            contacts_with_email=5_000,
            unsendable_addresses=25,
            unverified_addresses=200,
        )
    )
    assert borderline.verdict == "throttle" and borderline.throttle_factor == 0.5
    assert next(s for s in borderline.signals if s.metric == "bounce").proven


def test_a_metric_with_no_data_shrinks_the_evidence_rather_than_improving_the_score():
    no_sends = assess_risk(
        ObservedSignals(contacts_with_email=1_000, unsendable_addresses=200, unverified_addresses=400)
    )
    assert "2 of 6" in no_sends.coverage and "bounce" in no_sends.coverage
    # The list is bad, and the score says so even though four of six signals could not be measured.
    assert no_sends.risk_score > 0 and no_sends.verdict in ("caution", "throttle")


def test_a_low_reply_rate_counts_against_deliverability_not_only_against_the_copy():
    quiet = assess_risk(
        ObservedSignals(
            sent=10_000,
            bounced=50,
            replies=20,  # 0.2%: volume nobody answers
            accounts_touched=2_500,
            spam_complaints=0,
            unsubscribes=5,
            contacts_with_email=5_000,
            unsendable_addresses=25,
            unverified_addresses=200,
        )
    )
    reply = next(s for s in quiet.signals if s.metric == "reply")
    assert reply.status == "severe" and reply.severity == 1.0
    assert quiet.verdict == "throttle"  # severe, but not on a metric that stops a programme outright


def test_the_model_states_what_it_does_not_cover():
    covered = " ".join(DOES_NOT_MODEL).lower()
    for missing in ("ip reputation", "seed-list", "dkim", "inbox placement"):
        assert missing in covered
    assert "gtmos sends no email" in covered
    assert assess_risk(CLEAN).does_not_model == DOES_NOT_MODEL  # it travels with every assessment
