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
  prospectiveResearch?: {
    enabled: boolean;
    status: "NOT_REGISTERED" | "COLLECTING" | "READY" | "COMPLETED";
    studyId: string | null;
    freezeId: string | null;
    predictions: number;
    settledMatches: number;
    minimumSettledMatches: number;
    minimumCalendarDays: number;
    remainingMatches: number;
    remainingDays: number;
    confirmationDecision: string | null;
  };
  profitScorerOfficialSp?: {
    status: string;
    poolDiagnosisStatus?: string;
    poolScannedMatches?: number;
    poolScoredMatches?: number;
    poolPassedScorer?: number;
    poolBlockers?: string[];
    poolLastRunAt?: string | null;
    openingPreMatchSnapshots: number;
    frozenAttempts: number;
    frozenScoredAttempts: number;
    frozenBlockedAttempts: number;
    missedPreMatchAttempts: number;
    frozenEvidenceTemporalViolations: number;
    scoredSnapshots: number;
    selectedSnapshots: number;
    settledSelectedSnapshots: number;
    minimumSettledSelected: number;
    minimumMonths: number;
    remainingSettledSelected: number;
    decision: string | null;
    decisionReasons: string[];
    lastRunAt: string | null;
  };
  officialSpEvidenceQuality?: {
    decision: "NOT_RUN" | "EVIDENCE_READY" | "EVIDENCE_COLLECTING" | "EVIDENCE_DEGRADED" | "EVIDENCE_CRITICAL";
    research_usable: boolean;
    failed_checks: number;
    critical_checks: number;
    summary: {
      observations?: number;
      observed_matches?: number;
      pre_match_matches?: number;
      availability_observations?: number;
      offered_matches?: number;
      closing_eligible_matches?: number;
      freshness_hours?: number | null;
      pre_match_sp_coverage?: number;
      closing_1h_coverage?: number;
      settlement_coverage?: number;
    };
    checks: Array<{
      id: string;
      status: "PASS" | "PENDING" | "FAIL";
      severity: string;
      evidence: string;
      impact: string;
      remediation: string;
    }>;
  };
};

export type HealthTaskRun = NonNullable<SystemHealth["recentTaskRuns"]>[number];

export function latestTaskRunByName(rows: HealthTaskRun[] = []): Map<string, HealthTaskRun> {
  const latest = new Map<string, HealthTaskRun>();
  for (const row of rows) {
    const current = latest.get(row.task_name);
    const rowTime = Date.parse(row.started_at);
    const currentTime = current ? Date.parse(current.started_at) : Number.NEGATIVE_INFINITY;
    if (!current || (Number.isFinite(rowTime) && (!Number.isFinite(currentTime) || rowTime > currentTime))) {
      latest.set(row.task_name, row);
    }
  }
  return latest;
}

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
