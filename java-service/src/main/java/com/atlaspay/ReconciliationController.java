package com.atlaspay;

import java.util.Map;
import org.springframework.batch.core.Job;
import org.springframework.batch.core.JobExecution;
import org.springframework.batch.core.JobParametersBuilder;
import org.springframework.batch.core.launch.JobLauncher;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/reconciliation")
public class ReconciliationController {
  private final JobLauncher launcher;
  private final Job job;
  public ReconciliationController(JobLauncher launcher, Job reconciliationJob) { this.launcher = launcher; this.job = reconciliationJob; }

  @PostMapping("/runs")
  public ResponseEntity<Map<String, Object>> launch() throws Exception {
    JobExecution execution = launcher.run(job, new JobParametersBuilder().addLong("requestedAt", System.currentTimeMillis()).toJobParameters());
    return ResponseEntity.accepted().body(Map.of("executionId", execution.getId(), "status", execution.getStatus().name()));
  }
}