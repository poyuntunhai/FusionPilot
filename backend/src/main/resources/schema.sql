-- Declared first: fp_simulation_run, fp_user_session, fp_password_reset_token, fp_agent_session
-- and fp_dataset all carry a foreign key to it.
create table if not exists fp_user (
    user_id bigint primary key auto_increment,
    username varchar(50) not null,
    email varchar(190) not null,
    password_hash varchar(255) not null,
    display_name varchar(80) not null,
    role varchar(30) not null default 'USER',
    status varchar(30) not null default 'ACTIVE',
    last_login_at timestamp null,
    created_at timestamp not null default current_timestamp,
    updated_at timestamp not null default current_timestamp,
    constraint uk_fp_user_username unique (username),
    constraint uk_fp_user_email unique (email),
    index idx_fp_user_status (status),
    index idx_fp_user_created_at (created_at)
);

create table if not exists fp_simulation_run (
    run_id varchar(64) primary key,
    -- Nullable only for rows written before ownership was recorded; new runs always have an owner.
    user_id bigint null,
    scenario_name varchar(80) not null,
    target_count int not null,
    simulation_steps int not null,
    scheduling_policy varchar(40) not null,
    fusion_method varchar(40) not null default 'WEIGHTED_AVERAGE',
    random_seed bigint not null,
    average_position_error double not null,
    tracking_rate double not null,
    resource_utilization double not null,
    average_waiting_time double not null,
    scheduling_switches int not null,
    total_steps int not null,
    config_json longtext not null,
    result_json longtext not null,
    -- Only runs a user explicitly saved appear in that user's history list.
    saved boolean not null default false,
    -- Millisecond precision: runs finish within the same second, and both the history ordering
    -- and the unsaved-run cleanup need to tell them apart.
    saved_at timestamp(3) null,
    -- Per-user save order. Timestamps are not good enough: several saves land in the same
    -- millisecond, which would make "evict the oldest" depend on tie-breaking. This counter
    -- is monotonic per user, so both listing and eviction are exactly ordered.
    save_seq bigint null,
    completed_at timestamp(3) not null,
    index idx_fp_simulation_run_completed_at (completed_at),
    index idx_fp_simulation_run_policy (scheduling_policy),
    index idx_fp_simulation_run_owner_saved (user_id, saved, save_seq),
    constraint fk_simulation_run_user
        foreign key (user_id) references fp_user(user_id)
        on delete cascade
);
create table if not exists fp_simulation_step (
    step_id bigint primary key auto_increment,
    run_id varchar(64) not null,
    time_step int not null,
    created_at timestamp not null default current_timestamp,
    constraint fk_step_run
        foreign key (run_id) references fp_simulation_run(run_id)
        on delete cascade,
    constraint uk_step_run_time unique (run_id, time_step),
    index idx_step_run_time (run_id, time_step)
);

create table if not exists fp_target_truth (
    truth_id bigint primary key auto_increment,
    step_id bigint not null,
    target_id int not null,
    x double not null,
    y double not null,
    velocity_x double not null,
    velocity_y double not null,
    constraint fk_truth_step
        foreign key (step_id) references fp_simulation_step(step_id)
        on delete cascade,
    constraint uk_truth_step_target unique (step_id, target_id),
    index idx_truth_step_target (step_id, target_id)
);

create table if not exists fp_observation (
    observation_id bigint primary key auto_increment,
    step_id bigint not null,
    target_id int not null,
    source_type varchar(40) not null,
    available boolean not null,
    x double null,
    y double null,
    confidence double not null,
    constraint fk_observation_step
        foreign key (step_id) references fp_simulation_step(step_id)
        on delete cascade,
    index idx_observation_step_source_target (step_id, source_type, target_id),
    index idx_observation_available (available)
);

create table if not exists fp_fused_state (
    fused_state_id bigint primary key auto_increment,
    step_id bigint not null,
    target_id int not null,
    x double not null,
    y double not null,
    velocity_x double not null,
    velocity_y double not null,
    uncertainty double not null,
    association_confidence double not null,
    predicted_only boolean not null,
    constraint fk_fused_state_step
        foreign key (step_id) references fp_simulation_step(step_id)
        on delete cascade,
    constraint uk_fused_step_target unique (step_id, target_id),
    index idx_fused_step_target (step_id, target_id),
    index idx_fused_predicted_only (predicted_only)
);

create table if not exists fp_resource_assignment (
    assignment_id bigint primary key auto_increment,
    step_id bigint not null,
    target_id int not null,
    allocated boolean not null,
    priority_rank int not null,
    priority_score double not null,
    reason varchar(500) not null,
    constraint fk_assignment_step
        foreign key (step_id) references fp_simulation_step(step_id)
        on delete cascade,
    constraint uk_assignment_step_target unique (step_id, target_id),
    index idx_assignment_allocated_target (allocated, target_id),
    index idx_assignment_step_allocated (step_id, allocated)
);

create table if not exists fp_step_metric (
    step_metric_id bigint primary key auto_increment,
    step_id bigint not null,
    average_position_error double not null,
    tracking_rate double not null,
    resource_utilization double not null,
    allocated_target_count int not null,
    unserved_target_count int not null,
    constraint fk_step_metric_step
        foreign key (step_id) references fp_simulation_step(step_id)
        on delete cascade,
    constraint uk_metric_step unique (step_id)
);

create table if not exists fp_user_session (
    session_id bigint primary key auto_increment,
    user_id bigint not null,
    token_hash varchar(64) not null,
    expires_at timestamp not null,
    created_at timestamp not null default current_timestamp,
    revoked_at timestamp null,
    constraint fk_session_user
        foreign key (user_id) references fp_user(user_id)
        on delete cascade,
    constraint uk_fp_session_token_hash unique (token_hash),
    index idx_fp_session_user (user_id),
    index idx_fp_session_expiry (expires_at),
    index idx_fp_session_revoked (revoked_at)
);

create table if not exists fp_password_reset_token (
    reset_id bigint primary key auto_increment,
    user_id bigint not null,
    token_hash varchar(64) not null,
    expires_at timestamp not null,
    created_at timestamp not null default current_timestamp,
    used_at timestamp null,
    constraint fk_password_reset_user
        foreign key (user_id) references fp_user(user_id)
        on delete cascade,
    constraint uk_password_reset_token_hash unique (token_hash),
    index idx_password_reset_user (user_id),
    index idx_password_reset_expiry (expires_at),
    index idx_password_reset_used (used_at)
);

create table if not exists fp_agent_session (
    trace_id varchar(64) primary key,
    user_id bigint not null,
    goal varchar(1000) not null,
    status varchar(40) not null,
    confirmed boolean not null,
    plan_json longtext not null,
    events_json longtext not null,
    last_result_json longtext null,
    analysis_json longtext null,
    -- Multi-turn conversations are stored as one opaque snapshot. The snapshot carries the whole
    -- transcript, so a new conversation field never needs a schema change; these columns exist
    -- only so conversations can be listed without parsing JSON.
    snapshot_json longtext null,
    message_count int not null default 0,
    tool_call_count int not null default 0,
    model_label varchar(120) null,
    working_summary varchar(200) null,
    created_at timestamp not null default current_timestamp,
    updated_at timestamp not null default current_timestamp,
    constraint fk_agent_session_user
        foreign key (user_id) references fp_user(user_id)
        on delete cascade,
    index idx_agent_session_user_updated (user_id, updated_at),
    index idx_agent_session_status (status)
);

create table if not exists fp_dataset (
    dataset_id varchar(64) primary key,
    user_id bigint not null,
    file_name varchar(255) not null,
    file_size bigint not null,
    storage_path varchar(1000) not null,
    status varchar(30) not null,
    truth_rows int not null,
    observation_rows int not null,
    errors_json longtext not null,
    warnings_json longtext not null,
    created_at timestamp not null,
    constraint fk_dataset_user
        foreign key (user_id) references fp_user(user_id)
        on delete cascade,
    index idx_dataset_user_created (user_id, created_at),
    index idx_dataset_status (status)
);
