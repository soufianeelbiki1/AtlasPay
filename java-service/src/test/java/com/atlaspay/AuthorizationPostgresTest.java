package com.atlaspay;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import javax.sql.DataSource;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.ClassPathResource;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.PreparedStatementSetter;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.init.ResourceDatabasePopulator;
import org.springframework.test.context.junit.jupiter.SpringJUnitConfig;
import org.springframework.transaction.annotation.EnableTransactionManagement;
import org.springframework.web.server.ResponseStatusException;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import static org.junit.jupiter.api.Assertions.*;

@Testcontainers
@SpringJUnitConfig(AuthorizationPostgresTest.Config.class)
@Timeout(30)
class AuthorizationPostgresTest {
  @Container
  static final PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:16-alpine");

  @Configuration
  @EnableTransactionManagement
  static class Config {
    @Bean DataSource dataSource() {
      return new DriverManagerDataSource(postgres.getJdbcUrl(), postgres.getUsername(), postgres.getPassword());
    }
    @Bean RacingJdbcTemplate jdbc(DataSource source) { return new RacingJdbcTemplate(source); }
    @Bean DataSourceTransactionManager transactionManager(DataSource source) {
      return new DataSourceTransactionManager(source);
    }
    @Bean AuthorizationService service(RacingJdbcTemplate jdbc) {
      return new AuthorizationService(jdbc, new ObjectMapper());
    }
  }

  // Force both first reads to see no decision, rather than relying on timing.
  static class RacingJdbcTemplate extends JdbcTemplate {
    volatile CountDownLatch firstReads;
    RacingJdbcTemplate(DataSource source) { super(source); }
    @Override
    public <T> List<T> query(String sql, PreparedStatementSetter setter, RowMapper<T> mapper) {
      List<T> result = super.query(sql, setter, mapper);
      var barrier = firstReads;
      if (barrier != null && sql.contains("from authorization_decisions") && result.isEmpty()) {
        barrier.countDown();
        try {
          if (!barrier.await(10, TimeUnit.SECONDS)) throw new IllegalStateException("First reads did not overlap");
        } catch (InterruptedException exception) {
          Thread.currentThread().interrupt();
          throw new IllegalStateException(exception);
        }
      }
      return result;
    }
  }

  @Autowired AuthorizationService service;
  @Autowired RacingJdbcTemplate jdbc;
  @Autowired DataSource source;

  @BeforeEach
  void reset() {
    jdbc.firstReads = null;
    new ResourceDatabasePopulator(new ClassPathResource("schema.sql")).execute(source);
    jdbc.execute("create table if not exists outbox_events (id varchar primary key, aggregate_type varchar not null, aggregate_id varchar not null, event_type varchar not null, payload jsonb not null)");
    jdbc.execute("truncate authorization_decisions, outbox_events");
  }

  private AuthorizationController.AuthorizationRequest request(long amount) {
    return new AuthorizationController.AuthorizationRequest("pay-1", "issuer-1", amount, "EUR");
  }

  @Test
  void simultaneous_identical_requests_share_one_decision_and_event() throws Exception {
    jdbc.firstReads = new CountDownLatch(2);
    try (var pool = Executors.newFixedThreadPool(2)) {
      var first = pool.submit(() -> service.authorize("same-key", request(100)));
      var second = pool.submit(() -> service.authorize("same-key", request(100)));
      assertEquals(first.get(15, TimeUnit.SECONDS), second.get(15, TimeUnit.SECONDS));
    }
    assertEquals(1, jdbc.queryForObject("select count(*) from authorization_decisions", Integer.class));
    assertEquals(1, jdbc.queryForObject("select count(*) from outbox_events", Integer.class));
  }

  @Test
  void simultaneous_changed_requests_have_one_winner_and_one_conflict() throws Exception {
    jdbc.firstReads = new CountDownLatch(2);
    try (var pool = Executors.newFixedThreadPool(2)) {
      var first = pool.submit(() -> outcome(100));
      var second = pool.submit(() -> outcome(101));
      var outcomes = List.of(first.get(15, TimeUnit.SECONDS), second.get(15, TimeUnit.SECONDS));
      assertEquals(1, outcomes.stream().filter("approved"::equals).count());
      assertEquals(1, outcomes.stream().filter("conflict"::equals).count());
    }
    assertEquals(1, jdbc.queryForObject("select count(*) from authorization_decisions", Integer.class));
    assertEquals(1, jdbc.queryForObject("select count(*) from outbox_events", Integer.class));
  }

  private String outcome(long amount) {
    try {
      return service.authorize("same-key", request(amount)).status();
    } catch (ResponseStatusException exception) {
      assertEquals(409, exception.getStatusCode().value());
      return "conflict";
    }
  }

  @Test
  void outbox_failure_rolls_back_the_authorization_decision() {
    jdbc.execute("drop table outbox_events");
    assertThrows(DataAccessException.class, () -> service.authorize("rollback-key", request(100)));
    assertEquals(0, jdbc.queryForObject("select count(*) from authorization_decisions", Integer.class));
  }
}
