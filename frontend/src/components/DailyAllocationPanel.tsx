import useApi from "../hooks/useApi";
import type {OfficialMatch} from "../types";

type PaperRun = {
  run_id: string;
  decision_at: string;
  allocation_date: string;
  daily_budget: number;
  readiness_decision: string;
  allocated_budget: number;
  cash_reserved: number;
  status: "HOLD" | "ALLOCATED" | "NO_ELIGIBLE_POSITIONS";
  risk_multiplier: number | null;
};

type RiskState = {
  status: "NORMAL" | "REDUCED" | "PAUSED" | "RECOVERY";
  enforcement: "ACTIVE" | "SHADOW_ONLY";
  recommended_stake_multiplier: number;
  applied_stake_multiplier: number;
  consecutive_losing_settlement_days: number;
  current_drawdown: number;
  days_since_last_settlement: number | null;
};

type PaperPosition = {
  position_id: string;
  official_match_id: string;
  home_team: string;
  away_team: string;
  league: string;
  selected_outcome: "HOME" | "DRAW" | "AWAY";
  selected_sp: number;
  predicted_probability: number;
  predicted_ev: number;
  stake: number;
  placed_at: string;
  kickoff_time: string;
  actual_outcome: "HOME" | "DRAW" | "AWAY" | null;
  closing_sp: number | null;
  clv: number | null;
  profit: number | null;
  settled_at: string | null;
};

type PaperPortfolio = {
  method: string;
  runs: number;
  hold_runs: number;
  positions: number;
  open_positions: number;
  settled_positions: number;
  total_staked: number;
  profit: number;
  roi_pct: number;
  max_drawdown: number;
  closing_sp_coverage: number;
  average_clv: number | null;
  positive_clv_rate: number | null;
  risk_state: RiskState;
  recent_runs: PaperRun[];
  recent_positions: PaperPosition[];
  guardrail: string;
};

const empty: PaperPortfolio = {
  method: "immutable official-SP paper portfolio ledger",
  runs: 0,
  hold_runs: 0,
  positions: 0,
  open_positions: 0,
  settled_positions: 0,
  total_staked: 0,
  profit: 0,
  roi_pct: 0,
  max_drawdown: 0,
  closing_sp_coverage: 0,
  average_clv: null,
  positive_clv_rate: null,
  risk_state: {
    status: "NORMAL",
    enforcement: "SHADOW_ONLY",
    recommended_stake_multiplier: 1,
    applied_stake_multiplier: 1,
    consecutive_losing_settlement_days: 0,
    current_drawdown: 0,
    days_since_last_settlement: null,
  },
  recent_runs: [],
  recent_positions: [],
  guardrail: "仅进行纸面记账，不连接真实下单或支付接口。",
};

const outcomeLabel = {HOME: "主胜", DRAW: "平", AWAY: "客胜"} as const;
const pct = (value: number | null) => value === null ? "-" : `${(value * 100).toFixed(2)}%`;
const time = (value: string | null) => value ? new Date(value).toLocaleString("zh-CN", {hour12: false}) : "-";

export default function DailyAllocationPanel({matches: _matches}: {matches: OfficialMatch[]}) {
  const {data, loading, error} = useApi<PaperPortfolio>("/api/profit/paper-portfolio", empty);
  const latest = data.recent_runs[0];
  return <section className="panel" style={{marginTop: 16}}>
    <div className="panel-heading">
      <div>
        <h2>每日纸面投资组合账本</h2>
        <p>组合只来自后端不可变冻结记录。每日预算是风险上限，不要求必须投入，也不会自动真实下单。</p>
      </div>
      <span className={`status-tag ${latest?.status === "ALLOCATED" ? "success" : "warning"}`}>
        {latest?.status === "ALLOCATED" ? "已纸面建仓" : latest?.status === "HOLD" ? "保留现金" : "暂无合格持仓"}
      </span>
    </div>
    {loading && <p className="empty-state">正在读取纸面组合账本...</p>}
    {error && <p style={{padding: "0 16px", color: "var(--danger)"}}>账本读取失败：{error}</p>}
    <div className="summary-strip" style={{padding: 16, margin: 0}}>
      <span>每日上限<b>¥{(latest?.daily_budget ?? 100).toFixed(2)}</b></span>
      <span>本批纸面投入<b>¥{(latest?.allocated_budget ?? 0).toFixed(2)}</b></span>
      <span>现金保留<b>¥{(latest?.cash_reserved ?? 100).toFixed(2)}</b></span>
      <span>持仓 / 已结算<b>{data.positions} / {data.settled_positions}</b></span>
      <span>累计收益<b>¥{data.profit.toFixed(2)}</b></span>
      <span>ROI<b>{data.roi_pct.toFixed(2)}%</b></span>
      <span>最大回撤<b>¥{data.max_drawdown.toFixed(2)}</b></span>
      <span>动态风险状态<b>{data.risk_state.status}</b></span>
      <span>风险规则模式<b>{data.risk_state.enforcement === "ACTIVE" ? "已启用" : "影子观察"}</b></span>
      <span>建议 / 实际仓位倍数<b>{data.risk_state.recommended_stake_multiplier.toFixed(2)} / {data.risk_state.applied_stake_multiplier.toFixed(2)}</b></span>
      <span>平均 CLV<b>{pct(data.average_clv)}</b></span>
    </div>
    {latest && <p style={{padding: "0 16px"}}>
      最新决策：<code>{latest.readiness_decision}</code>，时间 {time(latest.decision_at)}。
    </p>}
    {data.recent_positions.length ? <div className="table-scroll"><table className="data-table">
      <thead><tr><th>比赛</th><th>方向</th><th>冻结概率</th><th>建仓 SP</th><th>当时 EV</th><th>纸面金额</th><th>结算</th><th>收益</th><th>CLV</th></tr></thead>
      <tbody>{data.recent_positions.map(row => <tr key={row.position_id}>
        <td>{row.home_team} vs {row.away_team}<br/><code>{row.official_match_id}</code></td>
        <td>{outcomeLabel[row.selected_outcome]}</td>
        <td>{pct(row.predicted_probability)}</td>
        <td>{row.selected_sp.toFixed(2)}</td>
        <td>{pct(row.predicted_ev)}</td>
        <td>¥{row.stake.toFixed(2)}</td>
        <td>{row.settled_at ? `${outcomeLabel[row.actual_outcome!]} / ${time(row.settled_at)}` : `待结算 / ${time(row.kickoff_time)}`}</td>
        <td>{row.profit === null ? "-" : `¥${row.profit.toFixed(2)}`}</td>
        <td>{pct(row.clv)}</td>
      </tr>)}</tbody>
    </table></div> : <p className="empty-state">资金门尚未通过，账本没有伪造持仓，当前全部保留现金。</p>}
    <p style={{padding: "0 16px", color: "var(--muted)"}}>{data.guardrail}</p>
  </section>;
}
