-- Business rule: an opportunity attributed to an outbound campaign must sit on an account that was
-- contacted first, and the contact must precede the opportunity.
--
-- Opportunities WITHOUT a source campaign are deliberately exempt: inbound, partner and referral
-- deals legitimately land on accounts outbound never touched (16 of them in the demo dataset), and
-- they are exactly the deals the attribution service reports as unattributed. Asserting "every
-- opportunity was contacted" would be a false rule that hides a real, correct behaviour.

select
    p.opportunity_id,
    p.account_id,
    p.campaign_id,
    p.opened_at,
    p.first_contacted_at
from {{ ref('fct_pipeline_snapshot') }} p
where p.is_campaign_sourced
  and (
    p.first_contacted_at is null
    or p.first_contacted_at > p.opened_at
  )
