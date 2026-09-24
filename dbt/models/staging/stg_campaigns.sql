-- Grain: one row per campaign_id -- a channel program running over a
-- defined [start_date, end_date] window. Period-level by nature, not event
-- grain (see generators/marketing_funnel.py's "Grain" section).
-- Light typing/renaming only: raw `name` is renamed to `campaign_name` so
-- the column isn't a bare `name` downstream. `channel` here is the finer
-- organic/paid/community sub-channel taxonomy, which DECOMPOSES the
-- `inbound_marketing` value of accounts.channel -- it is not a second,
-- competing channel field and carries no self_serve or outbound_sdr volume.

select
    campaign_id,
    name                            as campaign_name,
    channel,
    try_cast(start_date as date)    as start_date,
    try_cast(end_date as date)      as end_date,
    try_cast(budget as double)      as budget,
    try_cast(is_holdout as boolean) as is_holdout
from {{ source('raw', 'campaigns') }}
