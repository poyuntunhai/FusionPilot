package com.fusionpilot.backend.notice;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;

import java.sql.Timestamp;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Runs against the schema the application itself builds, which is the point: this project has
 * already shipped a table that existed in a migration but not in {@code schema.sql}, and the only
 * symptom was a silently dead feature. Anything the notice board needs must therefore be asserted
 * against the bootstrapped schema, not against a hand-written one in the test.
 *
 * <p>The read flag is the interesting part. It is per viewer and has to behave for three different
 * callers — a logged-out visitor, a user who has opened the message, and a different user who has
 * not — off a single query.
 */
@SpringBootTest
class SystemMessageRepositoryTest {

    @Autowired
    private SystemMessageRepository messages;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Test
    void theSchemaDefinesBothTablesWithTheColumnsTheRepositoryQueries() {
        assertThat(columnsOf("fp_system_message"))
                .contains("message_id", "title", "body", "version", "level", "published_at");
        assertThat(columnsOf("fp_system_message_read"))
                .contains("message_id", "user_id", "read_at");
    }

    @Test
    void aGuestSeesEveryMessageAsUnread() {
        long messageId = publish("维护通知", "今晚 22:00 重启服务。", "0.2.0", "INFO");

        List<SystemMessage> seenByGuest = messages.findPublished(null);

        SystemMessage message = find(seenByGuest, messageId);
        assertThat(message.title()).isEqualTo("维护通知");
        assertThat(message.version()).isEqualTo("0.2.0");
        assertThat(message.read()).isFalse();
    }

    @Test
    void theReadFlagFollowsTheViewerNotTheMessage() {
        long messageId = publish("版本更新", "新增系统消息中心。", "0.2.0", "UPDATE");
        long reader = newUser();
        long other = newUser();

        messages.markRead(messageId, reader);

        assertThat(find(messages.findPublished(reader), messageId).read()).isTrue();
        assertThat(find(messages.findPublished(other), messageId).read()).isFalse();
        assertThat(find(messages.findPublished(null), messageId).read()).isFalse();
    }

    @Test
    void readingTwiceKeepsOneReceipt() {
        long messageId = publish("重复打开", "点两次不应该产生两行。", null, "INFO");
        long userId = newUser();

        messages.markRead(messageId, userId);
        messages.markRead(messageId, userId);

        assertThat(receiptCount(messageId, userId)).isEqualTo(1);
    }

    @Test
    void messagesAreListedNewestFirst() {
        long older = publish("旧消息", "先发的。", null, "INFO");
        long newer = publish("新消息", "后发的。", null, "INFO");
        setPublishedAt(older, "2020-01-01 00:00:00");
        setPublishedAt(newer, "2024-01-01 00:00:00");

        List<SystemMessage> published = messages.findPublished(null);

        assertThat(indexOf(published, newer)).isLessThan(indexOf(published, older));
    }

    @Test
    void aMessageDatedInTheFutureIsNotListedYet() {
        long messageId = publish("定时公告", "发布时间还没到。", null, "INFO");
        setPublishedAt(messageId, "2099-01-01 00:00:00");

        assertThat(messages.findPublished(null))
                .noneMatch(message -> message.messageId() == messageId);
        // It has to be excluded from the read-receipt path too, or a client could mark a message
        // read before it was ever announced.
        assertThat(messages.existsPublished(messageId)).isFalse();
    }

    @Test
    void publishingReturnsTheGeneratedId() {
        long messageId = publish("给客户端用的 id", "发布接口要把新 id 返回给调用方。", null, "INFO");

        assertThat(messageId).isPositive();
        assertThat(find(messages.findPublished(null), messageId).title()).isEqualTo("给客户端用的 id");
    }

    private void setPublishedAt(long messageId, String timestamp) {
        // A java.sql.Timestamp rather than a string: H2 is strict enough about implicit VARCHAR to
        // TIMESTAMP conversion that the string form is not worth relying on.
        jdbcTemplate.update(
                "update fp_system_message set published_at = ? where message_id = ?",
                Timestamp.valueOf(timestamp), messageId);
    }

    private long publish(String title, String body, String version, String level) {
        return messages.insert(title, body, version, level);
    }

    private static SystemMessage find(List<SystemMessage> list, long messageId) {
        return list.stream()
                .filter(message -> message.messageId() == messageId)
                .findFirst()
                .orElseThrow(() -> new AssertionError("message " + messageId + " was not listed"));
    }

    private static int indexOf(List<SystemMessage> list, long messageId) {
        for (int index = 0; index < list.size(); index++) {
            if (list.get(index).messageId() == messageId) {
                return index;
            }
        }
        throw new AssertionError("message " + messageId + " was not listed");
    }

    private List<String> columnsOf(String table) {
        return jdbcTemplate.queryForList("""
                select lower(column_name) from information_schema.columns
                where lower(table_name) = ?
                """, String.class, table);
    }

    private int receiptCount(long messageId, long userId) {
        Integer count = jdbcTemplate.queryForObject(
                "select count(*) from fp_system_message_read where message_id = ? and user_id = ?",
                Integer.class, messageId, userId);
        return count == null ? 0 : count;
    }

    /** fp_system_message_read has a foreign key to fp_user, so a receipt needs a real user. */
    private long newUser() {
        String suffix = Long.toString(System.nanoTime(), 36);
        String username = "notice-" + suffix;
        jdbcTemplate.update("""
                insert into fp_user (username, email, password_hash, display_name)
                values (?, ?, ?, ?)
                """, username, username + "@test.local", "unused-hash", "NoticeTest");
        return jdbcTemplate.queryForObject(
                "select user_id from fp_user where username = ?", Long.class, username);
    }
}
