-- Grain: one row per rep_id -- account-owning reps only (rep_type ISR/AE).
-- SE and AM-Commercial/AM-Enterprise reps deliberately carry no row here at
-- all (not a null territory), since territory is a new-business coverage/
-- routing concept scoped to the roles that own accounts pre-close.

select
    rep_id,
    territory
from {{ source('raw', 'rep_territory') }}
