use fusionpilot;

-- Upgrade databases created before Agent session ownership and event snapshots
-- were added to the schema. Run once against an existing FusionPilot database.
alter table fp_agent_session
    add column user_id bigint not null after trace_id,
    add column events_json longtext not null after plan_json,
    add constraint fk_agent_session_user
        foreign key (user_id) references fp_user(user_id)
        on delete cascade,
    add index idx_agent_session_user_updated (user_id, updated_at);
