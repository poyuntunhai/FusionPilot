use fusionpilot;

-- Upgrade databases created before simulation runs carried an owner and a saved-history marker.
-- schema.sql only creates missing tables, so an existing database needs this run once.
--
-- user_id stays nullable on purpose: rows written before ownership was tracked have no owner,
-- and a nullable foreign key is exempt from the constraint. New runs always record an owner.

alter table fp_simulation_run
    add column user_id bigint null after run_id,
    add column fusion_method varchar(40) not null default 'WEIGHTED_AVERAGE' after scheduling_policy,
    add column saved boolean not null default false after result_json,
    add column saved_at timestamp(3) null after saved,
    add column save_seq bigint null after saved_at;

alter table fp_simulation_run
    add constraint fk_simulation_run_user
        foreign key (user_id) references fp_user(user_id)
        on delete cascade;

-- Supports both the per-user history listing and the newest-first cap eviction.
create index idx_fp_simulation_run_owner_saved
    on fp_simulation_run (user_id, saved, save_seq);
