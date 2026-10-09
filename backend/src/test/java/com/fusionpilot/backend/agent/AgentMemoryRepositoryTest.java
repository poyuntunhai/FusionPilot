package com.fusionpilot.backend.agent;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Covers the table the base schema had forgotten.
 *
 * Migration 006 added {@code fp_agent_memory}, but {@code schema.sql} — which is what actually
 * creates the schema on a new database, because the backend runs it on every start — was never
 * updated. On a fresh install the table simply did not exist: this repository threw, the memory
 * read endpoint answered 500, and because the agent's distillation step treats a failure as
 * best-effort, the write failure was swallowed. Long-term memory was dead and nothing said so.
 *
 * Every test here runs against the schema the application builds, so they fail if the table goes
 * missing again. Nothing else in the suite touches this repository.
 */
@SpringBootTest
class AgentMemoryRepositoryTest {

    @Autowired
    private AgentMemoryRepository memory;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Test
    void theSchemaDefinesTheMemoryTableWithTheColumnsTheRepositoryQueries() {
        List<String> columns = jdbcTemplate.queryForList("""
                select lower(column_name) from information_schema.columns
                where lower(table_name) = 'fp_agent_memory'
                """, String.class);

        assertThat(columns).contains("user_id", "memory_text", "updated_at");
    }

    @Test
    void aNoteRoundTripsThroughTheSchema() {
        long userId = newUser();

        assertThat(memory.get(userId)).isNull();

        memory.save(userId, "用户偏好先把目标数改成 5 再对比两种融合方法。");

        assertThat(memory.get(userId)).isEqualTo("用户偏好先把目标数改成 5 再对比两种融合方法。");
    }

    @Test
    void savingASecondNoteReplacesTheFirstInsteadOfAppending() {
        long userId = newUser();

        memory.save(userId, "first");
        memory.save(userId, "second");

        assertThat(memory.get(userId)).isEqualTo("second");
        assertThat(rowCount(userId)).isEqualTo(1);
    }

    @Test
    void aBlankNoteRemovesTheRow() {
        long userId = newUser();
        memory.save(userId, "something to forget");
        assertThat(rowCount(userId)).isEqualTo(1);

        memory.save(userId, "   ");

        assertThat(memory.get(userId)).isNull();
        assertThat(rowCount(userId)).isZero();
    }

    @Test
    void theNoteIsTrimmedBeforeItIsStored() {
        long userId = newUser();

        memory.save(userId, "  keep me  ");

        assertThat(memory.get(userId)).isEqualTo("keep me");
    }

    @Test
    void notesAreScopedToTheirOwner() {
        long mine = newUser();
        long theirs = newUser();

        memory.save(mine, "mine");
        memory.save(theirs, "theirs");

        assertThat(memory.get(mine)).isEqualTo("mine");
        assertThat(memory.get(theirs)).isEqualTo("theirs");
    }

    private int rowCount(long userId) {
        Integer count = jdbcTemplate.queryForObject(
                "select count(*) from fp_agent_memory where user_id = ?", Integer.class, userId);
        return count == null ? 0 : count;
    }

    /** fp_agent_memory has a foreign key to fp_user, so a note needs a real owner. */
    private long newUser() {
        String suffix = Long.toString(System.nanoTime(), 36);
        String username = "mem-" + suffix;
        jdbcTemplate.update("""
                insert into fp_user (username, email, password_hash, display_name)
                values (?, ?, ?, ?)
                """, username, username + "@test.local", "unused-hash", "MemoryTest");
        return jdbcTemplate.queryForObject(
                "select user_id from fp_user where username = ?", Long.class, username);
    }
}
