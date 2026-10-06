use fusionpilot;

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

create table if not exists fp_user (
    user_id bigint primary key auto_increment,
    username varchar(50) not null unique,
    email varchar(190) not null unique,
    password_hash varchar(255) not null,
    display_name varchar(80) not null,
    role varchar(30) not null default 'USER',
    status varchar(30) not null default 'ACTIVE',
    last_login_at timestamp null,
    created_at timestamp not null default current_timestamp,
    updated_at timestamp not null default current_timestamp on update current_timestamp,
    index idx_fp_user_status (status),
    index idx_fp_user_created_at (created_at)
);

create table if not exists fp_user_session (
    session_id bigint primary key auto_increment,
    user_id bigint not null,
    token_hash varchar(64) not null unique,
    expires_at timestamp not null,
    created_at timestamp not null default current_timestamp,
    revoked_at timestamp null,
    constraint fk_session_user
        foreign key (user_id) references fp_user(user_id)
        on delete cascade,
    index idx_fp_session_user (user_id),
    index idx_fp_session_expiry (expires_at),
    index idx_fp_session_revoked (revoked_at)
);

create table if not exists fp_password_reset_token (
    reset_id bigint primary key auto_increment,
    user_id bigint not null,
    token_hash varchar(64) not null unique,
    expires_at timestamp not null,
    created_at timestamp not null default current_timestamp,
    used_at timestamp null,
    constraint fk_password_reset_user
        foreign key (user_id) references fp_user(user_id)
        on delete cascade,
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
    created_at timestamp not null default current_timestamp,
    updated_at timestamp not null default current_timestamp on update current_timestamp,
    constraint fk_agent_session_user
        foreign key (user_id) references fp_user(user_id)
        on delete cascade,
    index idx_agent_session_user_updated (user_id, updated_at),
    index idx_agent_session_updated_at (updated_at),
    index idx_agent_session_status (status)
);

create table if not exists fp_agent_trace_event (
    event_id varchar(64) primary key,
    trace_id varchar(64) not null,
    event_type varchar(80) not null,
    payload_json longtext not null,
    created_at timestamp not null,
    constraint fk_trace_event_session
        foreign key (trace_id) references fp_agent_session(trace_id)
        on delete cascade,
    index idx_trace_event_trace_time (trace_id, created_at),
    index idx_trace_event_type (event_type)
);

create table if not exists fp_agent_tool_call (
    tool_call_id varchar(64) primary key,
    trace_id varchar(64) not null,
    tool_name varchar(120) not null,
    status varchar(40) not null,
    input_json longtext not null,
    result_json longtext null,
    error_message varchar(1000) null,
    started_at timestamp not null,
    completed_at timestamp null,
    constraint fk_tool_call_session
        foreign key (trace_id) references fp_agent_session(trace_id)
        on delete cascade,
    index idx_tool_call_trace_time (trace_id, started_at),
    index idx_tool_call_name_status (tool_name, status)
);
