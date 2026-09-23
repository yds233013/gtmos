"""The labelled dataset the lead-to-account matcher is evaluated on, and the harness that scores it.

This module exists because the matcher's old accuracy claim was circular: the fuzzy-name threshold was
chosen on the same 36 cases that were then used to report precision and recall. A threshold picked to look
good on a set cannot also be measured on it. So the data lives here, in one place, split once and
deterministically into a **development** half that tuning is allowed to see and a **held-out** half that it
is not, and `docs/matcher-evaluation.md` reports only the held-out half.

Three properties matter more than the size of the set:

1. **The split is a hash of the case id**, not a shuffle. Re-running on another machine, in another process
   or after adding cases cannot move an existing case from test to dev, so a number cannot be improved by
   re-rolling the dice.
2. **Every case carries its own justification** (`why`). The label is what a competent RevOps person would
   say the right answer is, and if that cannot be written down in a sentence the case does not belong here.
   Several families are genuinely contestable — subsidiaries above all — and those say so in their `why`.
3. **The mix is adversarial on purpose.** Near-duplicate company names, shared corporate domains, typos and
   brand labels on foreign TLDs are over-represented relative to real inbound traffic, where most leads
   arrive on a work email that matches an account exactly. The resulting numbers are therefore a floor on
   hard cases, not an estimate of production accuracy. `docs/matcher-evaluation.md` says this again, louder.

The data is synthetic and hand-labelled by one author, which means it encodes that author's assumptions
about what should match. It is evidence that the matcher behaves as designed on cases someone thought
about. It is not evidence about anyone's real CRM.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from gtmos.domain.experiments import wilson_interval
from gtmos.domain.matching import AccountRef, Lead, match_lead_to_account, normalize_domain

# The share of cases that go to the development split. Fixed once; moving it re-rolls every case's
# assignment, which is exactly the kind of quiet re-draw this design is meant to prevent.
DEV_SHARE_PERCENT = 50

# --- The account universe -------------------------------------------------------------------------------
#
# A CRM the matcher has to resolve against: ~45 accounts with the collisions a real one accumulates. Four
# collisions are deliberate and load-bearing, because a matcher that never sees them cannot be shown to be
# precise:
#   * two accounts on one corporate domain (Helio Robotics / Helio Medical, both helio.example),
#   * two accounts with the same name on different domains (Helio Robotics twice),
#   * two accounts sharing a brand label across TLDs (summit.example / summit.io, bluepeak.example /
#     bluepeak.io, quantstack.example / quantstack.de),
#   * two pairs of near-duplicate names (Acme Data / Acme Analytics, Kestrel Analytics / Kestrel Labs).
# Legal forms span the jurisdictions a B2B list actually contains, because "strip Inc" is not a plan.

EVAL_ACCOUNTS: tuple[AccountRef, ...] = (
    AccountRef("kestrel-analytics.example", "Kestrel Analytics", "kestrel-analytics.example", ("Kestrel Data Labs",)),
    AccountRef("kestrel-labs.example", "Kestrel Labs", "kestrel-labs.example"),
    AccountRef("northwind-logistics.example", "Northwind Logistics", "northwind-logistics.example"),
    AccountRef("meridian.co.uk", "Meridian Freight", "https://www.meridian.co.uk"),
    AccountRef("helio.example", "Helio Robotics", "helio.example", ("Sunburst Systems",)),
    AccountRef("helio-medical", "Helio Medical", "helio.example"),
    AccountRef("helio-robotics.example", "Helio Robotics", "helio-robotics.example"),
    AccountRef("acme-data.example", "Acme Data", "acme-data.example"),
    AccountRef("acme-analytics.example", "Acme Analytics", "acme-analytics.example"),
    AccountRef("sakura-ai.example", "さくらAI株式会社", "sakura-ai.example", ("Sakura AI",)),
    AccountRef("vertex-bio.example", "Vertex Bio GmbH", "vertex-bio.example"),
    AccountRef("orion.example", "Orion Manufacturing", "orion.example"),
    AccountRef("bluepeak.example", "Blue Peak Software", "bluepeak.example"),
    AccountRef("bluepeak.io", "Blue Peak Capital", "bluepeak.io"),
    AccountRef("cobalt-no-domain", "Cobalt Systems", None),
    AccountRef("summit.example", "Summit Health", "summit.example"),
    AccountRef("summit.io", "Summit Robotics", "summit.io"),
    AccountRef("aurora-labs.example", "Aurora Labs B.V.", "aurora-labs.example"),
    AccountRef("bergstrom.example", "Bergström Verkstad AB", "bergstrom.example"),
    AccountRef("tanaka-denki.example", "田中電機株式会社", "tanaka-denki.example", ("Tanaka Denki",)),
    AccountRef("hanwoori.example", "한우리소프트 주식회사", "hanwoori.example", ("Hanwoori Soft",)),
    AccountRef("lianhe.example", "联合科技有限公司", "lianhe.example", ("Lianhe Technology",)),
    AccountRef("delacroix.example", "Delacroix Logistique S.A.", "delacroix.example"),
    AccountRef("molinari.example", "Molinari Impianti S.p.A.", "molinari.example"),
    AccountRef("vandenberg.example", "Van den Berg Holding B.V.", "vandenberg.example"),
    AccountRef("southern-cross.com.au", "Southern Cross Mining Pty Ltd", "southern-cross.com.au"),
    AccountRef("kiwi-freight.co.nz", "Kiwi Freight Ltd", "kiwi-freight.co.nz"),
    AccountRef("patel-industries.co.in", "Patel Industries Pvt Ltd", "patel-industries.co.in"),
    AccountRef("nordvind.example", "Nordvind Energi ApS", "nordvind.example"),
    AccountRef("suomi-metsa.example", "Suomi Metsa Oyj", "suomi-metsa.example"),
    AccountRef("brightpath.example", "BrightPath Learning", "brightpath.example", ("Lumen Tutoring",)),
    AccountRef("ironclad-security.example", "Ironclad Security Inc", "ironclad-security.example"),
    AccountRef("ironclad.io", "Ironclad Contracts", "ironclad.io"),
    AccountRef("quantstack.example", "QuantStack Analytics", "quantstack.example"),
    AccountRef("quantstack.de", "QuantStack GmbH", "quantstack.de"),
    AccountRef("terra-verde.example", "Terra Verde Agriculture", "terra-verde.example"),
    AccountRef("terraverde.io", "TerraVerde Analytics", "terraverde.io"),
    AccountRef("lumina-health.example", "Lumina Health", "lumina-health.example"),
    AccountRef("pinecrest.example", "Pinecrest Capital", "pinecrest.example"),
    AccountRef("westbrook.co.uk", "Westbrook Partners LLP", "westbrook.co.uk"),
    AccountRef("atlas-freight.example", "Atlas Freight Systems", "atlas-freight.example"),
    AccountRef("atlas-bio.example", "Atlas Bioscience", "atlas-bio.example"),
    AccountRef("stellar-foods.com.br", "Stellar Alimentos Ltda", "stellar-foods.com.br"),
    AccountRef("maple-ridge.example", "Maple Ridge Dairy Co", "maple-ridge.example"),
    AccountRef("novacore.example", "NovaCore Systems", "novacore.example", ("Nova Core",)),
    AccountRef("helix-med.example", "Helix Medical Devices", "helix-med.example"),
    AccountRef("ridgeline.example", "Ridgeline Partners", "ridgeline.example"),
)

_BY_KEY = {a.key: a for a in EVAL_ACCOUNTS}


def _domain_of(key: str) -> str:
    """The account's domain, normalized. Raises if the account has none, so a typo cannot pass silently."""
    d = normalize_domain(_BY_KEY[key].domain)
    if d is None:  # pragma: no cover - a construction error in the table above, not a runtime condition
        raise ValueError(f"account {key!r} has no usable domain")
    return d


# --- Cases ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LabelledCase:
    """One lead, the account a human says it belongs to (or `None`), and why.

    `family` groups cases that share a failure mode, so the error taxonomy can be computed rather than
    asserted. `why` is the hand-check: if the label is ever disputed, this is the sentence to argue with.
    """

    case_id: str
    family: str
    lead: Lead
    expected: str | None
    why: str

    @property
    def split(self) -> str:
        return split_for(self.case_id)


def split_for(case_id: str) -> str:
    """Deterministic dev/test assignment from the case id alone.

    A hash, not `random.shuffle`: the assignment is a property of the case, reproducible on any machine and
    stable when cases are added or removed. `hash()` is not used because Python salts it per process.
    """
    digest = hashlib.blake2b(case_id.encode("utf-8"), digest_size=8).digest()
    return "dev" if int.from_bytes(digest, "big") % 100 < DEV_SHARE_PERCENT else "test"


def _build_cases() -> list[LabelledCase]:
    c: list[LabelledCase] = []

    def add(family: str, ident: str, lead: Lead, expected: str | None, why: str) -> None:
        c.append(LabelledCase(f"{family}/{ident}", family, lead, expected, why))

    # 1. Work email on the account's own domain. The unambiguous base case; the label is the domain.
    for local, key in (
        ("priya", "kestrel-analytics.example"),
        ("tom", "kestrel-labs.example"),
        ("dana", "northwind-logistics.example"),
        ("j.okafor", "meridian.co.uk"),
        ("mira", "acme-data.example"),
        ("ravi", "acme-analytics.example"),
        ("yuki", "sakura-ai.example"),
        ("klaus", "vertex-bio.example"),
        ("sam", "orion.example"),
        ("nina", "bluepeak.example"),
        ("omar", "summit.example"),
        ("lea", "aurora-labs.example"),
        ("anders", "bergstrom.example"),
        ("takeshi", "tanaka-denki.example"),
        ("minji", "hanwoori.example"),
        ("wei", "lianhe.example"),
        ("camille", "delacroix.example"),
        ("gio", "molinari.example"),
        ("pieter", "vandenberg.example"),
        ("bruce", "southern-cross.com.au"),
        ("aroha", "kiwi-freight.co.nz"),
        ("anita", "patel-industries.co.in"),
        ("freja", "nordvind.example"),
        ("aino", "suomi-metsa.example"),
        ("grace", "brightpath.example"),
        ("dmitri", "ironclad-security.example"),
        ("hana", "quantstack.example"),
        ("bea", "terra-verde.example"),
        ("ola", "lumina-health.example"),
        ("hugh", "westbrook.co.uk"),
    ):
        add(
            "exact_domain",
            key,
            Lead(email=f"{local}@{_domain_of(key)}"),
            key,
            f"Work email on {_domain_of(key)}, which is exactly this account's domain.",
        )

    # 2. The website field, with the noise a form actually collects: scheme, www, path, query, casing.
    for raw, key in (
        ("https://www.Northwind-Logistics.example/careers", "northwind-logistics.example"),
        ("http://acme-analytics.example", "acme-analytics.example"),
        ("terra-verde.example/about?utm_source=webinar", "terra-verde.example"),
        ("https://KIWI-FREIGHT.co.nz/", "kiwi-freight.co.nz"),
        ("www.stellar-foods.com.br", "stellar-foods.com.br"),
        ("https://helix-med.example:443/contact", "helix-med.example"),
        ("https://www.pinecrest.example", "pinecrest.example"),
        ("maple-ridge.example", "maple-ridge.example"),
    ):
        add(
            "website_field",
            key,
            Lead(website=raw),
            key,
            f"The website field resolves to {_domain_of(key)} once scheme, www, port and path are removed.",
        )

    # 3. A subdomain of a known account domain. Regional and functional subdomains are the company.
    for prefix, key in (
        ("eu", "kestrel-analytics.example"),
        ("mail", "meridian.co.uk"),
        ("shop", "orion.example"),
        ("careers", "brightpath.example"),
        ("emea.sales", "novacore.example"),
        ("go", "summit.io"),
        ("apac", "southern-cross.com.au"),
        ("intranet", "ridgeline.example"),
    ):
        add(
            "subdomain",
            f"{prefix}.{key}",
            Lead(email=f"p@{prefix}.{_domain_of(key)}"),
            key,
            f"{prefix}.{_domain_of(key)} is a subdomain of the account's own domain, so it is the same company.",
        )

    # 4. An explicit product group key (PostHog `$groups.company`) alongside a personal address. The group
    #    key is set by the product, not typed by the lead, so it outranks everything else on the record.
    for key, free in (
        ("kestrel-analytics.example", "gmail.com"),
        ("northwind-logistics.example", "yahoo.com"),
        ("quantstack.de", "outlook.com"),
        ("atlas-freight.example", "proton.me"),
        ("lumina-health.example", "icloud.com"),
        ("nordvind.example", "hotmail.com"),
    ):
        add(
            "group_key",
            key,
            Lead(email=f"user@{free}", group_domain=_domain_of(key)),
            key,
            f"The product's own company key is {_domain_of(key)}; the personal mailbox is irrelevant next to it.",
        )

    # 5. Role addresses. A shared inbox is still a company address: it matches the account, and whether it
    #    may become a Contact is a separate decision the caller makes.
    for local, key in (
        ("sales", "bluepeak.example"),
        ("info", "molinari.example"),
        ("support", "quantstack.example"),
        ("hello", "brightpath.example"),
        ("enquiries", "westbrook.co.uk"),
    ):
        add(
            "role_address",
            f"{local}@{key}",
            Lead(email=f"{local}@{_domain_of(key)}"),
            key,
            f"{local}@ is a shared inbox at {_domain_of(key)}, which is still that account's domain.",
        )

    # 6. The company name exactly as the CRM holds it, on a free-mail address. Consultants, founders and
    #    conference badge scans arrive like this constantly.
    for key, free in (
        ("kestrel-analytics.example", "gmail.com"),
        ("acme-data.example", "gmail.com"),
        ("acme-analytics.example", "yahoo.com"),
        ("orion.example", "outlook.com"),
        ("bluepeak.example", "hotmail.com"),
        ("summit.example", "icloud.com"),
        ("summit.io", "proton.me"),
        ("pinecrest.example", "gmx.com"),
        ("atlas-bio.example", "qq.com"),
        ("terraverde.io", "fastmail.com"),
        ("helix-med.example", "aol.com"),
        ("ridgeline.example", "zoho.com"),
        ("ironclad.io", "mail.com"),
        ("maple-ridge.example", "yandex.com"),
    ):
        add(
            "exact_name_freemail",
            key,
            Lead(email=f"person@{free}", company_name=_BY_KEY[key].name),
            key,
            f"The company name is exactly '{_BY_KEY[key].name}' as the CRM holds it; {free} carries no company.",
        )

    # 7. The same company with its legal form written differently, or left off. "Vertex Bio" and "Vertex Bio
    #    GmbH" are one company: legal form is a jurisdictional fact about the entity, not part of its identity.
    for typed, key in (
        ("Vertex Bio", "vertex-bio.example"),
        ("Kestrel Analytics, Inc.", "kestrel-analytics.example"),
        ("Northwind Logistics Ltd", "northwind-logistics.example"),
        ("Southern Cross Mining", "southern-cross.com.au"),
        ("Kiwi Freight", "kiwi-freight.co.nz"),
        ("Patel Industries", "patel-industries.co.in"),
        ("Nordvind Energi", "nordvind.example"),
        ("Suomi Metsa", "suomi-metsa.example"),
        ("Delacroix Logistique SA", "delacroix.example"),
        ("Molinari Impianti SpA", "molinari.example"),
        ("Aurora Labs BV", "aurora-labs.example"),
        ("Bergstrom Verkstad", "bergstrom.example"),
        ("Ironclad Security", "ironclad-security.example"),
        ("Maple Ridge Dairy", "maple-ridge.example"),
    ):
        add(
            "legal_suffix",
            f"{key}/{typed}",
            Lead(email="person@gmail.com", company_name=typed),
            key,
            f"'{typed}' is '{_BY_KEY[key].name}' with the legal form varied or dropped — the same entity.",
        )

    # 8. CJK names, with and without their legal forms, plus the romanized alias the CRM also stores.
    for typed, key in (
        ("さくらAI株式会社", "sakura-ai.example"),
        ("さくらAI", "sakura-ai.example"),
        ("田中電機株式会社", "tanaka-denki.example"),
        ("田中電機", "tanaka-denki.example"),
        ("한우리소프트", "hanwoori.example"),
        ("联合科技", "lianhe.example"),
        ("联合科技有限公司", "lianhe.example"),
    ):
        add(
            "cjk_name",
            f"{key}/{typed}",
            Lead(email="person@gmail.com", company_name=typed),
            key,
            f"'{typed}' is the account's registered name with the CJK legal form present or absent.",
        )

    # 9. DBA names, former names and acquired brands, which is how a CRM records a company people still
    #    call by its old name. The alias list is data the CRM already has; using it is not a guess.
    for typed, key in (
        ("Sunburst Systems", "helio.example"),
        ("Kestrel Data Labs", "kestrel-analytics.example"),
        ("Lumen Tutoring", "brightpath.example"),
        ("Nova Core", "novacore.example"),
        ("Sakura AI", "sakura-ai.example"),
        ("Tanaka Denki", "tanaka-denki.example"),
        ("Hanwoori Soft", "hanwoori.example"),
        ("Lianhe Technology", "lianhe.example"),
    ):
        add(
            "alias_name",
            f"{key}/{typed}",
            Lead(email="person@gmail.com", company_name=typed),
            key,
            f"'{typed}' is recorded on this account as an alias (DBA, former or acquired name).",
        )

    # 10. Casing and punctuation noise from a form field. None of it changes which company was meant.
    for typed, key in (
        ("KESTREL ANALYTICS", "kestrel-analytics.example"),
        ("northwind  logistics", "northwind-logistics.example"),
        ("Blue-Peak Software", "bluepeak.example"),
        ("terra verde agriculture", "terra-verde.example"),
        ("Atlas Freight Systems.", "atlas-freight.example"),
        ("pinecrest capital", "pinecrest.example"),
        ("HELIX MEDICAL DEVICES", "helix-med.example"),
    ):
        add(
            "name_noise",
            f"{key}/{typed}",
            Lead(email="person@gmail.com", company_name=typed),
            key,
            f"'{typed}' differs from '{_BY_KEY[key].name}' only in case, spacing or punctuation.",
        )

    # 11. A one-character typo in a hand-typed company name. A human reading this against the CRM picks the
    #     account without hesitating; the question is whether the matcher does, and at what cost elsewhere.
    for typed, key in (
        ("Kestrel Analtyics", "kestrel-analytics.example"),
        ("Northwind Logistcs", "northwind-logistics.example"),
        ("Blue Peak Softwre", "bluepeak.example"),
        ("Ironclad Secrity", "ironclad-security.example"),
        ("Lumina Helath", "lumina-health.example"),
        ("Pinecrest Captial", "pinecrest.example"),
        ("Atlas Bioscence", "atlas-bio.example"),
        ("Ridgeline Partnrs", "ridgeline.example"),
        ("Helix Medcal Devices", "helix-med.example"),
        ("Maple Rigde Dairy", "maple-ridge.example"),
        ("Terra Verde Agricultre", "terra-verde.example"),
    ):
        add(
            "name_typo",
            f"{key}/{typed}",
            Lead(email="person@gmail.com", company_name=typed),
            key,
            f"'{typed}' is '{_BY_KEY[key].name}' with one character mistyped; no other account is close.",
        )

    # 12. The company's country site, on a different TLD from the CRM's domain, with the company name to
    #     confirm it. The name is what makes this safe — the brand label alone is a weak key (see family 21).
    for host, key in (
        ("kestrel-analytics.de", "kestrel-analytics.example"),
        ("meridian.de", "meridian.co.uk"),
        ("northwind-logistics.fr", "northwind-logistics.example"),
        ("southern-cross.co.nz", "southern-cross.com.au"),
        ("terra-verde.es", "terra-verde.example"),
        ("brightpath.ca", "brightpath.example"),
    ):
        add(
            "cctld_brand",
            f"{key}/{host}",
            Lead(email=f"p@{host}", company_name=_BY_KEY[key].name),
            key,
            f"{host} is the same brand label as the account's domain on another TLD, and the company name agrees.",
        )

    # 13. A typo'd email domain and nothing else. The lead is that company — the label says so — but the
    #     matcher is designed never to fuzzy-match a domain, so these are known, accepted misses.
    for host, key in (
        ("kestrel-analytcs.example", "kestrel-analytics.example"),
        ("nothwind-logistics.example", "northwind-logistics.example"),
        ("bluepaek.example", "bluepeak.example"),
        ("quanstack.example", "quantstack.example"),
        ("terra-vrde.example", "terra-verde.example"),
    ):
        add(
            "typo_domain_only",
            f"{key}/{host}",
            Lead(email=f"p@{host}"),
            key,
            f"{host} is one character off the account's domain; a human reads it as {_domain_of(key)}.",
        )

    # 14. The same typo with the company name filled in — the mitigation the matcher relies on.
    for host, key in (
        ("kestrel-analytcs.example", "kestrel-analytics.example"),
        ("nothwind-logistics.example", "northwind-logistics.example"),
        ("bluepaek.example", "bluepeak.example"),
        ("lumnia-health.example", "lumina-health.example"),
        ("pincrest.example", "pinecrest.example"),
    ):
        add(
            "typo_domain_with_name",
            f"{key}/{host}",
            Lead(email=f"p@{host}", company_name=_BY_KEY[key].name),
            key,
            f"The domain is typo'd but the company name is exactly '{_BY_KEY[key].name}'.",
        )

    # 15. An account the CRM holds with no domain at all — common for accounts created from a conference
    #     list. The name is the only key there is, and it is enough.
    no_domain: tuple[tuple[str, str | None], ...] = (
        ("Cobalt Systems", "p@cobaltsystems.example"),
        ("Cobalt Systems Inc", "founder@gmail.com"),
        ("cobalt systems", None),
    )
    for typed, email in no_domain:
        add(
            "no_domain_account",
            typed,
            Lead(email=email, company_name=typed),
            "cobalt-no-domain",
            "The CRM's Cobalt Systems account has no domain, so the company name is the only available key.",
        )

    # 16. A malformed or empty email with a usable company name. The email is unusable; the name is not.
    for email, key in (
        ("not-an-email", "bluepeak.example"),
        ("priya@", "orion.example"),
        ("dana at northwind-logistics.example", "northwind-logistics.example"),
        ("", "summit.example"),
    ):
        add(
            "malformed_email",
            f"{key}/{email or 'empty'}",
            Lead(email=email, company_name=_BY_KEY[key].name),
            key,
            f"The email cannot be parsed, but '{_BY_KEY[key].name}' names the account exactly.",
        )

    # 17. A holding-company suffix the CRM does not carry. "Group" is deliberately never stripped as a legal
    #     form — a group is often a separate entity — but when the CRM has no separate group account, the
    #     operating company is the only defensible answer. This is a judgment call, and the weakest family
    #     here after subsidiaries.
    for typed, key in (
        ("Northwind Logistics Group", "northwind-logistics.example"),
        ("Meridian Freight Group", "meridian.co.uk"),
        ("Atlas Freight Systems Group", "atlas-freight.example"),
    ):
        add(
            "group_suffix",
            f"{key}/{typed}",
            Lead(email="person@gmail.com", company_name=typed),
            key,
            f"'{typed}' has no separate account in this CRM, so '{_BY_KEY[key].name}' is the only entity it can mean.",
        )

    # 18. Free-mail and nothing else. gmail.com is not a company; there is no right account.
    for free in ("gmail.com", "yahoo.com", "outlook.com", "proton.me", "qq.com", "googlemail.com"):
        add(
            "freemail_only",
            free,
            Lead(email=f"person@{free}"),
            None,
            f"{free} is a consumer mailbox with no company name attached; any match would be invented.",
        )

    # 19. A company that is simply not in the CRM. The correct answer is an unmatched lead.
    for name, host in (
        ("Zenith Unknown", "zenith-unknown.example"),
        ("Harbourline Shipping", "harbourline.example"),
        ("Pelagic Foods", "pelagic-foods.example"),
        ("Juniper Rail", "juniper-rail.example"),
        ("Castellan Insurance", "castellan.example"),
        ("Fenwick Dental", "fenwick-dental.example"),
        ("Oakmont Tooling", "oakmont.example"),
        ("Brightwater Utilities", "brightwater.example"),
        ("Velasco Textiles", "velasco.example"),
        ("Hargreaves Plant Hire", "hargreaves.example"),
    ):
        add(
            "unknown_company",
            host,
            Lead(email=f"p@{host}", company_name=name),
            None,
            f"No account in this CRM is {name}; the right outcome is an unmatched lead for review.",
        )

    # 20. The dangerous negatives: a company that shares a leading token with an account but is not it.
    #     These are the cases a lowered fuzzy threshold buys, and each one is a wrong rep on a real account.
    for name in (
        "Acme Insurance",
        "Acme Data Partners",
        "Kestrel Capital",
        "Kestrel Analytics Recruiting",
        "Orion Pharma",
        "Orion Medical",
        "Atlas Rentals",
        "Summit Legal",
        "Terra Firma Agriculture",
        "Lumina Studios",
        "Ironclad Fabrication",
        "Pinecrest Veterinary",
        "Blue Peak Roofing",
        "Northwind Marine",
    ):
        add(
            "near_miss_name",
            name,
            Lead(email="person@gmail.com", company_name=name),
            None,
            f"'{name}' shares a word with an account but is a different company; matching it routes a rep wrongly.",
        )

    # 21. A shared brand label on a foreign TLD with no company name to confirm it. 'orion.de' is Orion
    #     Pharma, not our Orion Manufacturing, and a domain alone cannot tell them apart.
    for host, note in (
        ("orion.de", "Orion is a common brand label; the CRM's Orion is a manufacturer."),
        ("atlas.fr", "Two Atlas accounts exist and neither owns the bare label."),
        ("summit.co", "Two Summit accounts share the label on different TLDs."),
        ("bluepeak.co", "Two Blue Peak accounts share the label on different TLDs."),
        ("quantstack.fr", "Two QuantStack accounts share the label on different TLDs."),
        ("terraverde.co.uk", "Terra Verde and TerraVerde are different accounts."),
    ):
        add(
            "brand_label_only",
            host,
            Lead(email=f"p@{host}"),
            None,
            f"{note} With no company name on the lead there is nothing to break the tie.",
        )

    # 22. A brand label on a foreign TLD where the company name actively contradicts the candidate.
    for host, name in (
        ("orion.de", "Orion Pharma"),
        ("atlas.fr", "Atlas Voyages"),
        ("summit.co", "Summit Coffee Roasters"),
    ):
        add(
            "brand_label_contradicted",
            f"{host}/{name}",
            Lead(email=f"p@{host}", company_name=name),
            None,
            f"'{name}' is not the account that owns this brand label, and says so on the record.",
        )

    # 23. Two accounts on one corporate domain. Picking either is a coin flip, so neither is the answer.
    for email, group in (
        ("p@helio.example", None),
        ("dana@eu.helio.example", None),
        ("sales@helio.example", None),
        ("person@gmail.com", "helio.example"),
    ):
        add(
            "shared_corporate_domain",
            email + (f"+{group}" if group else ""),
            Lead(email=email, group_domain=group),
            None,
            "helio.example belongs to both Helio Robotics and Helio Medical; the domain cannot choose between them.",
        )

    # 24. Two accounts with the same name. Same problem, on the name key.
    for typed in ("Helio Robotics", "Helio Robotics Inc", "helio robotics"):
        add(
            "duplicate_account_name",
            typed,
            Lead(email="person@gmail.com", company_name=typed),
            None,
            "Two accounts are named Helio Robotics; a CRM with duplicates needs a human, not a coin flip.",
        )

    # 25. A bare parent brand with several children. "Acme" is not enough information to route anything.
    for typed in ("Acme", "Summit", "Atlas", "Helio", "Kestrel", "QuantStack"):
        add(
            "bare_brand",
            typed,
            Lead(email="person@gmail.com", company_name=typed),
            None,
            f"'{typed}' names a family of accounts, not one of them.",
        )

    # 26. Subsidiaries. The most contestable family in this set, and it splits two ways on purpose:
    #     a subsidiary on the parent's own brand domain is reachable from the parent account, while one
    #     with its own name AND its own domain is a separate entity the CRM does not hold. Both labels are
    #     arguable, and a different revenue team would draw the line somewhere else.
    subsidiaries: tuple[tuple[str, str, str | None, str], ...] = (
        (
            "kestrel-analytics.jp",
            "Kestrel Analytics Japan",
            "kestrel-analytics.example",
            "A country arm on the parent's brand domain, with no separate account: the parent is the only entity.",
        ),
        (
            "meridian.ie",
            "Meridian Freight Ireland",
            "meridian.co.uk",
            "A country arm on the parent's brand domain, with no separate account: the parent is the only entity.",
        ),
        (
            "northwind-freight.example",
            "Northwind Freight Solutions",
            None,
            "A different name on a different domain: a separate legal entity the CRM does not hold.",
        ),
        (
            "helio-diagnostics.example",
            "Helio Diagnostics",
            None,
            "A different name on a different domain, and the Helio accounts are already ambiguous.",
        ),
        (
            "brightpath-ventures.example",
            "BrightPath Ventures",
            None,
            "An investment arm with its own domain; matching it to the learning business would route the wrong rep.",
        ),
        (
            "quantstack-labs.example",
            "QuantStack Labs",
            None,
            "A research spin-out on its own domain, with two QuantStack accounts already competing for the label.",
        ),
    )
    for host, name, parent, why in subsidiaries:
        add("subsidiary", host, Lead(email=f"p@{host}", company_name=name), parent, why)

    # 27. Exact domain wins over a company name pointing somewhere else. The lead works at the company that
    #     owns their mailbox; a mistyped or stale company field does not outrank it.
    for email, typed, key in (
        ("p@acme-data.example", "Acme Analytics", "acme-data.example"),
        ("p@kestrel-labs.example", "Kestrel Analytics", "kestrel-labs.example"),
        ("p@summit.io", "Summit Health", "summit.io"),
    ):
        add(
            "domain_beats_name",
            f"{key}/{typed}",
            Lead(email=email, company_name=typed),
            key,
            f"The mailbox is at {key}'s own domain; the company field is stale or wrong, and the domain is not.",
        )

    # 28. Near-duplicate accounts named exactly. The pair exists to prove the matcher can still tell them
    #     apart when the name is unambiguous.
    for typed, key in (
        ("Acme Data", "acme-data.example"),
        ("Acme Analytics", "acme-analytics.example"),
        ("Kestrel Labs", "kestrel-labs.example"),
        ("Atlas Freight Systems", "atlas-freight.example"),
        ("Atlas Bioscience", "atlas-bio.example"),
        ("Ironclad Contracts", "ironclad.io"),
        ("Ironclad Security Inc", "ironclad-security.example"),
        ("TerraVerde Analytics", "terraverde.io"),
        ("QuantStack Analytics", "quantstack.example"),
        ("Blue Peak Capital", "bluepeak.io"),
    ):
        add(
            "near_duplicate_exact",
            f"{key}/{typed}",
            Lead(email="person@gmail.com", company_name=typed),
            key,
            f"'{typed}' is one half of a confusable pair, named exactly; the other half must not win.",
        )

    # 29. Names that sit between two accounts. A human cannot say which company this is either, so the only
    #     correct answer is to abstain and let someone look.
    for typed, why in (
        (
            "Acme Data Analytics",
            "Equally readable as Acme Data or Acme Analytics; no human could call this without asking.",
        ),
        ("Atlas Bio Freight", "Sits between Atlas Bioscience and Atlas Freight Systems."),
        ("Ironclad Security Contracts", "Sits between Ironclad Security and Ironclad Contracts."),
        ("Summit Health Robotics", "Sits between Summit Health and Summit Robotics."),
    ):
        add("genuinely_ambiguous_name", typed, Lead(email="person@gmail.com", company_name=typed), None, why)

    return c


EVAL_CASES: tuple[LabelledCase, ...] = tuple(_build_cases())
DEV_CASES: tuple[LabelledCase, ...] = tuple(c for c in EVAL_CASES if c.split == "dev")
TEST_CASES: tuple[LabelledCase, ...] = tuple(c for c in EVAL_CASES if c.split == "test")


# --- Scoring --------------------------------------------------------------------------------------------

# A match to the wrong account is counted twice on purpose: once as a false positive (an account acquired a
# lead that is not theirs) and once as a false negative (the right account never heard about it). One
# mistake, two victims, and a matcher that guesses should not be scored as if it merely abstained.
OUTCOME_KINDS = ("true_match", "wrong_match", "missed_match", "false_match", "true_abstain")


@dataclass(frozen=True)
class CaseOutcome:
    case: LabelledCase
    predicted: str | None
    method: str
    kind: str
    review_required: bool


@dataclass(frozen=True)
class Scoreboard:
    n: int
    tp: int
    fp: int
    fn: int
    tn: int
    precision: float
    recall: float
    f1: float
    precision_ci: tuple[float, float]
    recall_ci: tuple[float, float]
    outcomes: tuple[CaseOutcome, ...]

    @property
    def errors(self) -> tuple[CaseOutcome, ...]:
        return tuple(o for o in self.outcomes if o.kind in ("wrong_match", "missed_match", "false_match"))


def classify(case: LabelledCase, predicted: str | None) -> str:
    if case.expected is not None and predicted == case.expected:
        return "true_match"
    if case.expected is not None and predicted is not None:
        return "wrong_match"
    if case.expected is not None:
        return "missed_match"
    if predicted is not None:
        return "false_match"
    return "true_abstain"


def f_beta(precision: float, recall: float, beta: float = 1.0) -> float:
    """F-beta. beta < 1 weights precision above recall, which is the trade this matcher wants."""
    if precision <= 0.0 or recall <= 0.0:
        return 0.0
    b2 = beta * beta
    return (1 + b2) * precision * recall / (b2 * precision + recall)


def score_cases(
    cases: Sequence[LabelledCase],
    threshold: float,
    accounts: Sequence[AccountRef] = EVAL_ACCOUNTS,
) -> Scoreboard:
    """Run the matcher over a set of cases at one fuzzy threshold and build the confusion matrix."""
    outcomes = []
    for case in cases:
        m = match_lead_to_account(case.lead, accounts, fuzzy_threshold=threshold)
        outcomes.append(CaseOutcome(case, m.account_key, m.method, classify(case, m.account_key), m.review_required))
    counts = {k: sum(1 for o in outcomes if o.kind == k) for k in OUTCOME_KINDS}
    tp = counts["true_match"]
    fp = counts["wrong_match"] + counts["false_match"]
    fn = counts["wrong_match"] + counts["missed_match"]
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    return Scoreboard(
        n=len(outcomes),
        tp=tp,
        fp=fp,
        fn=fn,
        tn=counts["true_abstain"],
        precision=precision,
        recall=recall,
        f1=f_beta(precision, recall, 1.0),
        # Wilson treats each denominator as fixed. The precision denominator (matches attempted) is itself
        # random, so this interval is a little narrower than the truth; it is still far better than none.
        precision_ci=wilson_interval(tp, tp + fp),
        recall_ci=wilson_interval(tp, tp + fn),
        outcomes=tuple(outcomes),
    )


def bootstrap_interval(
    outcomes: Sequence[CaseOutcome],
    metric: str = "f1",
    iterations: int = 2000,
    seed: int = 20260922,
) -> tuple[float, float]:
    """Percentile bootstrap over cases, for metrics Wilson cannot cover.

    F1 is a ratio of two proportions that share a numerator, so no closed-form binomial interval applies.
    Resampling the cases themselves also honours what Wilson ignores: both denominators move together.
    The seed is fixed, so the reported interval is reproducible rather than a number that drifts per run.
    """
    if not outcomes:
        return (0.0, 0.0)
    rng = random.Random(seed)
    kinds = [o.kind for o in outcomes]
    n = len(kinds)
    samples = []
    for _ in range(iterations):
        drawn = [kinds[rng.randrange(n)] for _ in range(n)]
        tp = drawn.count("true_match")
        wrong = drawn.count("wrong_match")
        fp = wrong + drawn.count("false_match")
        fn = wrong + drawn.count("missed_match")
        p = tp / (tp + fp) if tp + fp else 1.0
        r = tp / (tp + fn) if tp + fn else 1.0
        samples.append({"f1": f_beta(p, r), "precision": p, "recall": r}[metric])
    samples.sort()
    lo = samples[int(0.025 * (iterations - 1))]
    hi = samples[int(0.975 * (iterations - 1))]
    return (lo, hi)


# Thresholds swept during tuning. The floor is 0.70 because below it the fuzzy tier matches on shared
# tokens alone; the ceiling is 0.98 because above it the tier is off in all but name.
CANDIDATE_THRESHOLDS: tuple[float, ...] = tuple(round(0.70 + 0.01 * i, 2) for i in range(29))

# Precision is weighted twice as heavily as recall, because the two errors are not equally expensive: a
# lead attached to the wrong account sends the wrong rep to a real customer and nothing raises, while a
# missed lead lands in an unmatched queue a human already reads. This is chosen before looking at the
# curve, not fitted to it.
TUNING_BETA = 0.5


@dataclass(frozen=True)
class TuningRow:
    threshold: float
    precision: float
    recall: float
    f1: float
    f_beta: float
    tp: int
    fp: int
    fn: int


def tuning_curve(
    cases: Sequence[LabelledCase] = DEV_CASES,
    thresholds: Iterable[float] = CANDIDATE_THRESHOLDS,
) -> tuple[TuningRow, ...]:
    """Threshold vs precision/recall on the development split. Never call this with `TEST_CASES`."""
    rows = []
    for t in thresholds:
        s = score_cases(cases, t)
        rows.append(
            TuningRow(t, s.precision, s.recall, s.f1, f_beta(s.precision, s.recall, TUNING_BETA), s.tp, s.fp, s.fn)
        )
    return tuple(rows)


def choose_threshold(rows: Sequence[TuningRow]) -> float:
    """The selection rule, fixed in advance: maximise F0.5, and break ties toward the higher threshold.

    Ties are broken upward rather than downward because on a plateau the more conservative threshold makes
    the same decisions on the cases we have and fewer guesses on the cases we do not.
    """
    best = max(rows, key=lambda r: (round(r.f_beta, 6), r.threshold))
    return best.threshold
