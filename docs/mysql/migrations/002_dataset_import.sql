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
