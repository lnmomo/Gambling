import type {SystemHealth} from "./healthService";

export function summarizeSystemHealth(health: SystemHealth) {
  const successfulTasks = health.recentTaskRuns?.filter(task => task.status === "SUCCESS").length ?? 0;
  const failedTasks = health.recentTaskRuns?.filter(task => task.status === "FAILED").length ?? 0;
  return {
    statusLabel: health.status === "healthy" ? "Healthy" : health.status === "degraded" ? "Degraded" : "Unhealthy",
    taskSummary: `${successfulTasks} success / ${failedTasks} failed`,
    databaseLabel: health.database.connected ? "Connected" : "Disconnected",
    apiKeyLabel: health.config.oddsApiKeyConfigured ? "Configured" : "Missing",
    autoBettingLabel: "Disabled",
    warningCount: health.warnings.length,
  };
}

export function formatHealthTime(value: string | null) {
  return value ? new Date(value).toLocaleString("zh-CN") : "-";
}
