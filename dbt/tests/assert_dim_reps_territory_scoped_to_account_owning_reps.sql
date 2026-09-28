-- territory is a new-business coverage/routing concept scoped to
-- account-owning reps only (rep_type ISR/AE): stg_rep_territory carries no
-- row at all for SE/AM-Commercial/AM-Enterprise reps. dim_reps.territory
-- must therefore be non-null if and only if rep_type is ISR or AE --
-- both directions. A dbt test passes when this query returns zero rows.

select
    rep_id,
    rep_type,
    territory
from {{ ref('dim_reps') }}
where (rep_type in ('ISR', 'AE') and territory is null)
   or (rep_type not in ('ISR', 'AE') and territory is not null)
