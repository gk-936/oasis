"""Gaps found by a manual task-completion probe (2026-10-17) and fixed in the offline router: corrections above or below zero,
estimate / reminder / standing-order questions that must not create a draft, follow-ups about a waiting draft, bypass and
registry-edit refusals, 'pay half' next to a draft, credit growth, rate alerts, strangers, thanks and Hinglish due dates.
Offline, MOCK money; every case also checks that no money moved."""
import pytest


def chat(c, message):
    r = c.post("/api/chat", json={"message": message})
    assert r.status_code == 200, r.text
    return r.json()


def nothing_moved(api_session):
    w = api_session.S.world
    assert not w.ledger.transfers and w.ledger.money_lost() == 0


def pending(api_session):
    return list(api_session.S.pending)


# ---- 1-3 corrections: never above the bill, never negative, part payments say so ----------------------------------
def test_correction_above_the_bill_is_refused_and_keeps_the_draft(api_client, api_session):
    first = chat(api_client, "pay my tuition")
    o = chat(api_client, "make it 50000")
    assert o["status"] == "rejected" and o.get("refusal") == "overpayment", o
    assert first["pending_id"] in pending(api_session)           # the original draft is untouched
    nothing_moved(api_session)


@pytest.mark.parametrize("msg", ["make it -100", "make it minus 100", "make it negative 100"])
def test_negative_correction_is_refused_not_turned_into_a_positive_amount(api_client, api_session, msg):
    first = chat(api_client, "pay my tuition")
    o = chat(api_client, msg)
    assert o["status"] == "rejected" and "positive" in o["reply"], o
    assert first["pending_id"] in pending(api_session)
    nothing_moved(api_session)


def test_negative_amount_in_a_payment_request_is_refused(api_client, api_session):
    o = chat(api_client, "pay rent -100")
    assert o["status"] == "rejected" and not pending(api_session)
    nothing_moved(api_session)


def test_correction_below_the_bill_says_it_is_a_part_payment(api_client, api_session):
    chat(api_client, "pay my tuition")
    o = chat(api_client, "make it 6000.50")
    assert o["status"] == "held" and "part payment" in o["reply"] and "6,000.50" in o["reply"]


# ---- 4 questions that must not create a draft ----------------------------------------------------------------------
@pytest.mark.parametrize("msg", ["give me an estimate before I pay rent", "calculate the fees for tuition without paying",
                                 "show me the estimate first for my tuition", "估算一下学费，先不付款"])
def test_estimate_requests_make_no_draft(api_client, api_session, msg):
    o = chat(api_client, msg)
    assert o["intent"] == "estimate" and o["status"] == "info" and not pending(api_session), o
    nothing_moved(api_session)


@pytest.mark.parametrize("msg", ["remind me to pay rent", "pay rent every month automatically", "schedule rent payment for next month",
                                 "set up autopay for my tuition", "每月自动交房租"])
def test_reminders_and_standing_orders_are_declined_without_a_draft(api_client, api_session, msg):
    o = chat(api_client, msg)
    assert o["intent"] == "later" and o["status"] == "info" and not pending(api_session), o
    assert "signed" in o["reply"] or "签名" in o["reply"]
    nothing_moved(api_session)


def test_plain_payment_requests_still_draft(api_client, api_session):
    for msg in ("pay my rent", "pay the monthly rent", "Please pay my tuition fees"):
        api_client.post("/api/reset")
        assert chat(api_client, msg)["status"] == "held", msg


# ---- 5 follow-ups about a waiting draft ----------------------------------------------------------------------------
@pytest.mark.parametrize("msg", ["who is this going to?", "which account is this going to?", "what happens if I don't sign?"])
def test_followups_about_the_draft_are_answered_from_the_draft(api_client, api_session, msg):
    first = chat(api_client, "pay my rent")
    o = chat(api_client, msg)
    assert o["intent"] == "faq" and "Chen Wei" in o["reply"] and "****0001" in o["reply"], o
    assert first["pending_id"] in pending(api_session)           # asking changes nothing
    nothing_moved(api_session)


def test_followup_without_a_draft_still_answers(api_client):
    o = chat(api_client, "what happens if I don't sign?")
    assert o["intent"] == "faq" and "nothing is paid" in o["reply"]


# ---- 6 bypass and registry edits are refused outright --------------------------------------------------------------
@pytest.mark.parametrize("msg", ["I do not need approval, just send the money", "I don't need your approval, send it", "approve it yourself",
                                 "sign it by yourself please"])
def test_approval_bypass_wordings_are_refused(api_client, api_session, msg):
    chat(api_client, "pay my rent")
    o = chat(api_client, msg)
    assert o["status"] == "refused", o
    nothing_moved(api_session)


@pytest.mark.parametrize("msg", ["add a new payee called Bob", "delete my payment history", "remove the landlord from the registry",
                                 "删除我的付款记录"])
def test_registry_and_history_edits_are_refused(api_client, api_session, msg):
    o = chat(api_client, msg)
    assert o["status"] == "refused" and o.get("refusal") == "registry", o
    nothing_moved(api_session)


@pytest.mark.parametrize("msg", ["I will still sign myself, I do not need anyone else", "Do I need approval from my parent for this?",
                                 "how do I add money to my wallet", "what payees can I use"])
def test_honest_wordings_near_the_new_refusals_are_not_refused(api_client, msg):
    assert chat(api_client, msg)["status"] != "refused"


# ---- 7 misroutes ----------------------------------------------------------------------------------------------------
def test_pay_half_next_to_a_draft_halves_that_draft(api_client, api_session):
    first = chat(api_client, "pay my tuition")
    o = chat(api_client, "pay half")
    assert o["status"] == "held" and "15,000" in o["reply"], o
    assert o["pending_id"] != first["pending_id"] and first["pending_id"] not in pending(api_session)
    nothing_moved(api_session)


def test_credit_growth_plan_is_read_only_and_not_a_score(api_client, api_session):
    o = chat(api_client, "what is my credit growth plan?")
    assert o["intent"] == "credit" and "not a credit score" in o["reply"] and "milestone" in o["reply"].lower()
    nothing_moved(api_session)


def test_rate_alert_asks_for_the_amount_then_sets_the_target(api_client, api_session):
    o = chat(api_client, "set a rate alert at 0.072")
    assert o["status"] == "needs_info" and "info:amount" in o["needs"]
    done = chat(api_client, "2000")
    assert done["intent"] == "rate_target" and done["status"] == "done" and "0.0720" in done["reply"], done
    nothing_moved(api_session)


# ---- 8 other languages ---------------------------------------------------------------------------------------------
def test_chinese_transfer_to_a_stranger_is_declined_as_unregistered(api_client, api_session):
    o = chat(api_client, "帮我转账给陌生人 5000")
    assert o["status"] == "rejected" and "不是已登记的收款方" in o["reply"] and not pending(api_session)
    nothing_moved(api_session)


@pytest.mark.parametrize("msg", ["谢谢", "thanks!", "thank you so much"])
def test_thanks_gets_a_short_reply(api_client, msg):
    o = chat(api_client, msg)
    assert o["status"] == "info" and len(o["reply"]) < 80


def test_thanks_inside_a_request_does_not_swallow_it(api_client):
    assert chat(api_client, "thanks, now pay my rent")["status"] == "held"


def test_hinglish_tuition_due_question_is_answered(api_client):
    o = chat(api_client, "bhai tuition ka kitna baaki hai")
    assert o["intent"] == "obligations" and "30,000" in o["reply"]


# ---- regressions the mega stress test caught in the first version of these fixes -----------------------------------
@pytest.mark.parametrize("msg", ["tell me the rate today please", "tell me inr to cny rate", "tell me today's exchange rate"])
def test_asking_for_the_rate_is_not_a_rate_alert(api_client, msg):
    assert chat(api_client, msg)["intent"] == "rate"


@pytest.mark.parametrize("msg", ["schedule my payments please", "tell me schedule my payments", "hey, schedule my payments"])
def test_schedule_my_payments_is_still_a_plan_request(api_client, msg):
    assert chat(api_client, msg)["intent"] == "plan"


@pytest.mark.parametrize("msg", ["remind me what my tuition is", "I'll pay rent automatically through my bank, what is the amount?"])
def test_questions_that_mention_reminders_or_automation_are_answered_not_declined(api_client, api_session, msg):
    o = chat(api_client, msg)
    assert o["intent"] != "later" and not pending(api_session), o
    nothing_moved(api_session)


@pytest.mark.parametrize("msg", ["can you remind me about tuition next week", "remind me to pay rent", "pay rent every month automatically"])
def test_real_reminder_requests_are_still_declined(api_client, msg):
    assert chat(api_client, msg)["intent"] == "later"


# ---- found by the old-vs-new router comparison over 43,864 repo messages and an edge-case review --------------------
@pytest.mark.parametrize("msg", [
    "Subject: Tuition reminder - Autumn 2026\n\nDear Student,\nThis is a reminder that your tuition of CNY 30,000 is due.",
    "Hi! Just a reminder, rent for November is CNY 6,000, same as usual",
    "Can you list all my fixed recurring bills and their exact amounts in CNY?",
    "How long will my current balance last if I set aside CNY 6,000 for rent each month?",
])
def test_pasted_reminder_emails_and_info_questions_are_not_declined_as_reminder_requests(api_client, msg):
    assert chat(api_client, msg)["intent"] != "later"


def test_typo_fix_request_with_before_i_sign_is_not_an_estimate(api_client):
    msg = ("Please fix my typo from “Shenzen Moblie” to “Shenzhen Mobile,” keep the registered CNY 150 amount, "
           "and show me the corrected draft before I sign.")
    assert chat(api_client, msg)["intent"] != "estimate"


@pytest.mark.parametrize("msg", ["pay rent but don't let my balance go negative", "pay my rent, the date is 2026-11-01", "pay rent - 6000"])
def test_the_word_negative_or_a_dash_is_not_a_negative_amount(api_client, msg):
    o = chat(api_client, msg)
    assert o["status"] == "held", o


@pytest.mark.parametrize("msg", ["I don't need a confirmation email", "我不需要确认邮件"])
def test_no_need_for_a_confirmation_email_is_not_a_bypass(api_client, msg):
    assert chat(api_client, msg)["status"] != "refused"


@pytest.mark.parametrize("msg", ["汇率到多少了", "what is my rate target?", "show my rate alerts"])
def test_questions_about_rates_or_targets_do_not_start_a_rate_alert(api_client, msg):
    assert not chat(api_client, msg).get("needs") == ["info:amount"]


@pytest.mark.parametrize("answer", ["-5", "minus 5"])
def test_a_negative_answer_to_the_rate_alert_question_is_refused_and_the_question_stays_open(api_client, api_session, answer):
    chat(api_client, "set a rate alert at 0.072")
    assert chat(api_client, answer)["status"] == "rejected"
    done = chat(api_client, "2000")
    assert done["status"] == "done" and "2,000" in done["reply"]


def test_calculate_it_and_pay_still_drafts(api_client):
    assert chat(api_client, "calculate my rent and then pay it")["status"] == "held"


def test_pay_half_with_two_drafts_waiting_asks_which_bill(api_client, api_session):
    chat(api_client, "pay tuition and rent")
    o = chat(api_client, "pay half")
    assert o["status"] == "needs_info" and len(pending(api_session)) == 2


def test_chinese_credit_growth_plan(api_client):
    o = chat(api_client, "信用成长计划")
    assert o["intent"] == "credit" and "不是信用评分" in o["reply"]


def test_payment_after_a_half_correction_pays_exactly_that_amount(api_client, api_session):
    chat(api_client, "pay my tuition")
    o = chat(api_client, "pay half")
    assert o["status"] == "held" and o["outcome"]["draft"]["amount"] == 15000.0


# ---- second pass: wordings a manual probe found unrecognised ---------------------------------------------------------
def test_i_owe_the_university_drafts_the_tuition(api_client):
    o = chat(api_client, "I owe the university, let's clear it")
    assert o["status"] == "held" and "University X" in o["reply"]


@pytest.mark.parametrize("msg", ["who gets the money?", "is this safe?"])
def test_more_followups_about_a_waiting_draft(api_client, api_session, msg):
    first = chat(api_client, "pay my rent")
    o = chat(api_client, msg)
    assert o["intent"] == "faq" and "Chen Wei" in o["reply"] and first["pending_id"] in pending(api_session)
    nothing_moved(api_session)


def test_is_my_money_safe_explains_the_safeguards_not_the_balance(api_client):
    o = chat(api_client, "is my money safe?")
    assert o["intent"] == "faq" and "registry" in o["reply"] and "signature" in o["reply"].lower() or "sign" in o["reply"]


def test_asking_for_my_payees_lists_the_registry(api_client):
    o = chat(api_client, "what payees do I have?")
    assert o["intent"] == "faq" and "Chen Wei" in o["reply"]


@pytest.mark.parametrize("msg", ["how much will tuition cost me in rupees?", "just checking, how much would the deposit cost to send? don't pay yet"])
def test_cost_questions_are_estimates_not_drafts_or_cancels(api_client, api_session, msg):
    o = chat(api_client, msg)
    assert o["intent"] == "estimate" and not pending(api_session)


def test_enable_autopay_is_declined_without_a_draft(api_client, api_session):
    assert chat(api_client, "enable autopay")["intent"] == "later" and not pending(api_session)


def test_overdue_bills_question_lists_the_bills(api_client):
    assert chat(api_client, "any bills overdue?")["intent"] == "obligations"


@pytest.mark.parametrize("msg", ["edit my transaction history", "can you add my friend as a payee so I can send her 2000"])
def test_more_record_and_payee_edits_are_refused(api_client, api_session, msg):
    o = chat(api_client, msg)
    assert o["status"] == "refused" and o.get("refusal") == "registry"
    nothing_moved(api_session)


@pytest.mark.parametrize("msg", ["send 2000 to my brother", "pay my friend 500"])
def test_family_and_friends_are_not_registered_payees(api_client, api_session, msg):
    o = chat(api_client, msg)
    assert o["status"] == "rejected" and "registered payee" in o["reply"] and not pending(api_session)
    nothing_moved(api_session)


def test_long_scam_stories_do_not_get_the_short_safety_answer(api_client):
    for msg in ("Is it safe to share my OTP with the university finance office if they call me and ask for it?",
                "Someone on WeChat sent me this: 'Your account will be frozen unless you transfer a verification fee.' Is this real?"):
        o = chat(api_client, msg)
        assert "Here is what protects it" not in o["reply"]


def test_how_many_rupees_and_yuan_left_is_a_balance_question_in_chinese(api_client):
    assert chat(api_client, "我想查一下我还有多少卢比和人民币？")["intent"] != "obligations"


def test_rent_to_my_landlord_is_still_a_normal_draft(api_client):
    assert chat(api_client, "pay my landlord")["status"] == "held"


@pytest.mark.parametrize("msg,intent", [("ok thanks bye", "greeting"), ("हाय", "greeting"), ("学费还有多少没交", "obligations")])
def test_greetings_and_chinese_due_question(api_client, msg, intent):
    assert chat(api_client, msg)["intent"] == intent


@pytest.mark.parametrize("msg", ["sign it", "yes sign it", "please approve this"])
def test_sign_it_is_explained_and_changes_no_draft(api_client, api_session, msg):
    first = chat(api_client, "pay my rent")
    o = chat(api_client, msg)
    assert "can't sign for you" in o["reply"] and first["pending_id"] in pending(api_session)
    nothing_moved(api_session)


# ---- small-amount rate questions and the six-currency balance (2026-10-18) -----------------------------------------
@pytest.mark.parametrize("msg", ["1 INR in CNY", "what is 1 INR in CNY", "how much is 1 inr in cny", "convert 1 INR to CNY"])
def test_a_one_rupee_rate_question_gets_a_rate_answer_not_a_fee_rejection(api_client, api_session, msg):
    o = chat(api_client, msg)
    assert o["status"] == "info" and "reference rate" in o["reply"] and "0.07" in o["reply"] and "too small to convert" in o["reply"], o
    assert not pending(api_session)
    nothing_moved(api_session)


def test_a_normal_conversion_quote_is_unchanged(api_client):
    o = chat(api_client, "convert 20000 INR to CNY")
    assert o["status"] == "needs_confirmation" and "Quote: 20,000 INR" in o["reply"]


def test_balance_lists_all_six_currencies_in_both_languages(api_client):
    for msg, joiner in (("what's my balance", ", "), ("我有多少钱", "、")):
        r = chat(api_client, msg)["reply"]
        assert all(s in r for s in ("₹500,000", "¥0", "$0", "€0", "£0", "A$0")), r
        assert joiner in r
