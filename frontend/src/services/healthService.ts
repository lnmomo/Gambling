export type HealthStatus = "healthy" | "degraded" | "unhealthy";
export type SyncStatus = "OK" | "STALE" | "FAILED" | "UNKNOWN";

export type SystemHealth = {
  status: HealthStatus;
  appEnv: string;
  database: {connected: boolean; urlConfigured: boolean};
  officialSpSync: {lastSuccessAt: string | null; status: SyncStatus};
  externalOddsSync: {lastSuccessAt: string | null; status: SyncStatus};
  model: {championVersion: string | null; stackingEnabled: boolean; challengerAvailable: boolean};
  config: {
    realSyncEnabled: boolean;
    autoBettingEnabled: false;
    autoBettingRequested?: boolean;
    oddsApiKeyConfigured: boolean;
    databaseUrlConfigured?: boolean;
    logLevel?: string;
  };
  recentErrors: number;
  warnings: string[];
  recentTaskRuns?: Array<{
    id: string;
    task_name: string;
    started_at: string;
    finished_at: string | null;
    status: "SUCCESS" | "FAILED" | "SKIPPED" | "RUNNING";
    attempts: number;
    error_message: string | null;
    affected_matches: number | null;
    created_snapshots: number | null;
    created_predictions: number | null;
    warnings: string[];
  }>;
  dataQuality?: {invalidSnapshots: number; duplicateSkipped: number; staleSnapshots: number};
};

export async function fetchSystemHealth(): Promise<SystemHealth> {
  try {
    const response = await fetch("/health");
    if (!response.ok) throw new Error(`health check failed (${response.status})`);
    return await response.json();
  } catch (error) {
    return {
      status: "unhealthy",
      appEnv: "unknown",
      database: {connected: false, urlConfigured: false},
      officialSpSync: {lastSuccessAt: null, status: "UNKNOWN"},
      externalOddsSync: {lastSuccessAt: null, status: "UNKNOWN"},
      model: {championVersion: null, stackingEnabled: false, challengerAvailable: false},
      config: {realSyncEnabled: false, autoBettingEnabled: false, oddsApiKeyConfigured: false},
      recentErrors: 1,
      warnings: ["后端健康检查不可用", error instanceof Error ? error.message : "unknown error"],
      recentTaskRuns: [],
      dataQuality: {invalidSnapshots: 0, duplicateSkipped: 0, staleSnapshots: 0},
    };
  }
}
