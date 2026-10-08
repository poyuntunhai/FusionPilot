use fusionpilot;

-- completed_at was second-precision, which is too coarse to order runs that finish in the same
-- second. That made "keep the most recent unsaved runs" depend on arbitrary tie-breaking.
-- Widening it to milliseconds gives real ordering; existing rows keep their second value.
--
-- Safe to run repeatedly: MODIFY COLUMN is idempotent for the same target definition.

alter table fp_simulation_run
    modify column completed_at timestamp(3) not null;
