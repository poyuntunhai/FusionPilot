create table if not exists fp_simulation_run (
    run_id varchar(64) primary key,
    scenario_name varchar(80) not null,
    target_count int not null,
    simulation_steps int not null,
    scheduling_policy varchar(40) not null,
    random_seed bigint not null,
    average_position_error double not null,
    tracking_rate double not null,
    resource_utilization double not null,
    average_waiting_time double not null,
    scheduling_switches int not null,
    total_steps int not null,
    config_json longtext not null,
    result_json longtext not null,
    completed_at timestamp not null,
    index idx_fp_simulation_run_completed_at (completed_at),
    index idx_fp_simulation_run_policy (scheduling_policy)
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
