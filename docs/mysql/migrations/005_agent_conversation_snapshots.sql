use fusionpilot;

-- Multi-turn agent conversations.
--
-- A conversation is stored as one opaque snapshot in snapshot_json. The transcript shape keeps
-- growing (tool calls, evidence rows, pending decisions), and encoding that as columns would mean
-- a migration for every addition. The scalar columns beside it exist purely so the conversation
-- list can be rendered and sorted without parsing the snapshot.
--
-- schema.sql only creates missing tables, so an existing database needs this run once.

alter table fp_agent_session
    add column snapshot_json longtext null after analysis_json,
    add column message_count int not null default 0 after snapshot_json,
    add column tool_call_count int not null default 0 after message_count,
    add column model_label varchar(120) null after tool_call_count,
    add column working_summary varchar(200) null after model_label;
