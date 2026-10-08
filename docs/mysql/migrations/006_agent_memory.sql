-- Long-term per-user agent memory.
-- One row per user holding the agent's own distilled notes (preferences, findings) so a new
-- conversation starts with context instead of from scratch.

create table if not exists fp_agent_memory (
    user_id bigint primary key,
    memory_text text not null,
    updated_at timestamp not null default current_timestamp,
    constraint fk_agent_memory_user
        foreign key (user_id) references fp_user(user_id)
        on delete cascade
);
