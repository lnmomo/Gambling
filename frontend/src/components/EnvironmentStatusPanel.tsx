import type {SystemHealth} from "../services/healthService";

export default function EnvironmentStatusPanel({health}:{health:SystemHealth}) {
  return <section className="panel">
    <div className="panel-heading"><div><h2>Environment</h2><p>前端只展示配置状态，不展示真实密钥或完整敏感路径。</p></div></div>
    <section className="summary-strip" style={{padding:16,margin:0}}>
      <span>APP_ENV<b>{health.appEnv}</b></span>
      <span>DATABASE_URL<b>{health.database.urlConfigured ? "Configured" : "Missing"}</b></span>
      <span>THE_ODDS_API_KEY<b>{health.config.oddsApiKeyConfigured ? "Configured" : "Missing"}</b></span>
      <span>ENABLE_REAL_SYNC<b>{health.config.realSyncEnabled ? "true" : "false"}</b></span>
      <span>ENABLE_STACKING_MODEL<b>{health.model.stackingEnabled ? "true" : "false"}</b></span>
      <span>ENABLE_AUTO_BETTING<b>Disabled</b></span>
      <span>LOG_LEVEL<b>{health.config.logLevel ?? "-"}</b></span>
    </section>
    <p className="muted">复制 `.env.example` 为 `.env` 后填写本机配置。不要把 `.env`、真实 db、真实 CSV 或 API key 提交到 Git。</p>
  </section>;
}
