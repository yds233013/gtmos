-- Business rule: within a campaign week, an email cannot be delivered, opened, replied to or bounced
-- more times than it was sent. A violation means either a double-counted webhook or an activity
-- landing in the wrong campaign, both of which would silently inflate every downstream reply rate.

select
    campaign_id,
    activity_week,
    emails_sent,
    emails_delivered,
    emails_bounced,
    replies
from {{ ref('fct_outbound_performance') }}
where emails_delivered + emails_bounced > emails_sent
   or replies > emails_sent
   or positive_replies > replies
