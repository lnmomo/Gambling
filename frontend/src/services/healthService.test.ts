import {describe, expect, it} from "vitest";
import {latestTaskRunByName, type HealthTaskRun} from "./healthService";

const run = (id: string, task: string, startedAt: string, status: HealthTaskRun["status"]): HealthTaskRun => ({
  id,
  task_name: task,
  started_at: startedAt,
  finished_at: status === "RUNNING" ? null : startedAt,
  status,
  attempts: 1,
  error_message: null,
  affected_matches: 0,
  created_snapshots: 0,
  created_predictions: 0,
  warnings: [],
});

describe("latestTaskRunByName", () => {
  it("keeps the newest run even when an older row appears later", () => {
    const rows = [
      run("new", "historical_data_sync", "2026-06-19T04:37:21+00:00", "SUCCESS"),
      run("old", "historical_data_sync", "2026-06-17T14:03:32+00:00", "RUNNING"),
    ];

    expect(latestTaskRunByName(rows).get("historical_data_sync")?.id).toBe("new");
  });

  it("does not depend on backend ordering", () => {
    const rows = [
      run("old", "official_sp_sync", "2026-06-17T14:03:32+00:00", "SUCCESS"),
      run("new", "official_sp_sync", "2026-06-19T04:37:21+00:00", "RUNNING"),
    ];

    expect(latestTaskRunByName(rows).get("official_sp_sync")?.id).toBe("new");
  });
});
