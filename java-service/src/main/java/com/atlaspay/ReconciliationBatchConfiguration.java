package com.atlaspay;

import java.time.Instant;
import java.util.UUID;
import javax.sql.DataSource;
import org.springframework.batch.core.Job;
import org.springframework.batch.core.Step;
import org.springframework.batch.core.job.builder.JobBuilder;
import org.springframework.batch.core.repository.JobRepository;
import org.springframework.batch.core.step.builder.StepBuilder;
import org.springframework.batch.item.ItemProcessor;
import org.springframework.batch.item.database.JdbcBatchItemWriter;
import org.springframework.batch.item.database.JdbcCursorItemReader;
import org.springframework.batch.item.database.builder.JdbcBatchItemWriterBuilder;
import org.springframework.batch.item.database.builder.JdbcCursorItemReaderBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.context.annotation.Configuration;
import org.springframework.transaction.PlatformTransactionManager;

@Configuration
public class ReconciliationBatchConfiguration {
  public record ReconciliationItem(UUID itemId, String paymentId, String expectedStatus, String observedStatus, long amountMinor) {}
  public record ReconciliationResult(UUID itemId, String paymentId, String matchStatus, long deltaMinor, Instant processedAt) {}

  @Bean
  JdbcCursorItemReader<ReconciliationItem> reconciliationReader(DataSource dataSource) {
    return new JdbcCursorItemReaderBuilder<ReconciliationItem>()
      .name("reconciliationReader").dataSource(dataSource)
      .sql("select item_id,payment_id,expected_status,observed_status,amount_minor from reconciliation_items where processed_at is null order by created_at,item_id")
      .rowMapper((rs, rowNum) -> new ReconciliationItem(rs.getObject("item_id", UUID.class), rs.getString("payment_id"), rs.getString("expected_status"), rs.getString("observed_status"), rs.getLong("amount_minor")))
      .build();
  }

  @Bean
  ItemProcessor<ReconciliationItem, ReconciliationResult> reconciliationProcessor() {
    return item -> {
      String match = item.expectedStatus().equals(item.observedStatus()) ? "MATCHED" : "MISMATCH";
      return new ReconciliationResult(item.itemId(), item.paymentId(), match, 0L, Instant.now());
    };
  }

  @Bean
  JdbcBatchItemWriter<ReconciliationResult> reconciliationWriter(DataSource dataSource) {
    return new JdbcBatchItemWriterBuilder<ReconciliationResult>().dataSource(dataSource)
      .sql("insert into reconciliation_results(item_id,payment_id,match_status,delta_minor,processed_at) values (:itemId,:paymentId,:matchStatus,:deltaMinor,:processedAt) on conflict (item_id) do update set match_status=excluded.match_status,delta_minor=excluded.delta_minor,processed_at=excluded.processed_at")
      .itemSqlParameterSourceProvider(item -> new MapSqlParameterSource()
        .addValue("itemId", item.itemId()).addValue("paymentId", item.paymentId())
        .addValue("matchStatus", item.matchStatus()).addValue("deltaMinor", item.deltaMinor())
        .addValue("processedAt", item.processedAt())).build();
  }

  @Bean
  Step reconciliationStep(JobRepository jobRepository, PlatformTransactionManager transactionManager, JdbcCursorItemReader<ReconciliationItem> reader, ItemProcessor<ReconciliationItem, ReconciliationResult> processor, JdbcBatchItemWriter<ReconciliationResult> writer) {
    return new StepBuilder("reconciliationStep", jobRepository).<ReconciliationItem, ReconciliationResult>chunk(100, transactionManager).reader(reader).processor(processor).writer(writer).build();
  }

  @Bean
  Job reconciliationJob(JobRepository jobRepository, Step reconciliationStep) {
    return new JobBuilder("reconciliationJob", jobRepository).start(reconciliationStep).build();
  }
}