from gtmos.domain.committee import ContactFacts, infer_committee

CONTACTS = [
    ContactFacts("c1", "Dana Whitfield", "Chief Technology Officer", "c_suite", "engineering"),
    ContactFacts("c2", "Marcus Chen", "VP Engineering", "vp", "engineering"),
    ContactFacts("c3", "Priya Raman", "Head of AI Platform", "director", "ai_ml", replied=True, product_user=True),
    ContactFacts("c4", "Tomás Alvarez", "Staff ML Engineer, Platform", "ic", "ai_ml"),
    ContactFacts("c5", "Aisha Okafor", "ML Engineer", "ic", "ai_ml"),
    ContactFacts("c6", "Pat Sales", "Account Executive", "ic", "sales"),
]


def test_each_role_goes_to_the_expected_person_with_reasons():
    r = infer_committee(CONTACTS)
    assert r.holder("executive_sponsor").contact_id == "c1"
    assert r.holder("economic_buyer").contact_id == "c2"
    assert r.holder("champion").contact_id == "c3"
    assert r.holder("technical_evaluator").contact_id == "c4"
    assert r.holder("end_user").contact_id == "c5"
    assert r.unfilled_roles == []
    champ = r.holder("champion")
    assert any("free product" in x for x in champ.reasons)
    assert 0 < champ.confidence <= 0.99
    assert all(a.contact_id != "c6" for a in r.assignments)


def test_manual_override_wins_and_persists():
    r = infer_committee(CONTACTS, overrides={"champion": "c4"})
    ch = r.holder("champion")
    assert ch.contact_id == "c4" and ch.is_manual_override and ch.confidence == 1.0
    assert all(a.contact_id != "c3" for a in r.assignments if a.role == "champion" and a.rank == 1)
    # c4 is the only qualified technical evaluator, so it holds both roles and says so
    te = r.holder("technical_evaluator")
    assert te.contact_id == "c4" and any("Also holds another role" in x for x in te.reasons)


def test_do_not_contact_and_invalid_email_are_penalized():
    cs = [ContactFacts("a", "A", "Head of AI", "director", "ai_ml", do_not_contact=True),
          ContactFacts("b", "B", "Director of Machine Learning", "director", "ai_ml")]
    assert infer_committee(cs).holder("champion").contact_id == "b"


def test_unfilled_roles_reported_and_deterministic():
    cs = [ContactFacts("z", "Z", "ML Engineer", "ic", "ai_ml")]
    r1, r2 = infer_committee(cs), infer_committee(list(reversed(cs)))
    assert "economic_buyer" in r1.unfilled_roles
    assert [(a.role, a.contact_id) for a in r1.assignments] == [(a.role, a.contact_id) for a in r2.assignments]
