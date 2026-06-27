import {useMemo, useState} from "react";
import {buildDailyAllocationPlan} from "../algorithm/dailyAllocation";
import type {OfficialMatch} from "../types";

const pct = (value: number) => `${(value * 100).toFixed(2)}%`;
const outcomeLabel = {HOME: "主胜", DRAW: "平", AWAY: "客胜"} as const;

export default function DailyAllocationPanel({matches}: {matches: OfficialMatch[]}) {
  const [budget, setBudget] = useState(100);
  const plan = useMemo(() => buildDailyAllocationPlan(matches, budget), [matches, budget]);
  return <section className="panel" style={{marginTop: 16}}>
    <div className="panel-heading">
      <div><h2>每日定额资金方案</h2><p>每日预算是风险上限，不是必须投入金额；系统不会自动下注，也不保证收益。</p></div>
      <label>每日预算 ¥ <input type="number" min="0" max="100" step="10" value={budget} onChange={event => setBudget(Math.min(100, Math.max(0, Number(event.target.value) || 0)))} style={{width: 100}}/></label>
    </div>
    <div className="summary-strip" style={{padding: 16, margin: 0}}>
      <span>预算上限<b>¥{plan.budget.toFixed(2)}</b></span>
      <span>实际候选分配<b>¥{plan.executableAllocated.toFixed(2)}</b></span>
      <span>现金保留<b>¥{plan.cashReserve.toFixed(2)}</b></span>
      <span>实际候选<b>{plan.executable.length}</b></span>
      <span>影子候选<b>{plan.shadowSimulated.length}</b></span>
    </div>
    {plan.warnings.map(warning => <p key={warning} style={{padding: "0 16px", color: "var(--warning)"}}>{warning}</p>)}
    {plan.executable.length > 0 && <div className="table-scroll"><table className="data-table"><thead><tr><th>实际候选</th><th>方向</th><th>概率</th><th>官方赔率</th><th>预期收益率</th><th>风险</th><th>建议额度</th></tr></thead><tbody>{plan.executable.map(row => <tr key={row.matchId}><td>{row.match}<br/><code>{row.officialMatchId}</code></td><td>{outcomeLabel[row.outcome]}</td><td>{pct(row.probability)}</td><td>{row.officialSp.toFixed(2)}</td><td>{pct(row.ev)}</td><td>{row.riskLevel}</td><td>¥{row.amount.toFixed(2)}</td></tr>)}</tbody></table></div>}
    <div className="panel-heading" style={{paddingTop: 16}}><div><h3>影子模拟组合</h3><p>按最高 EV 生成每日研究样本，仅用于跟踪、回测和验证，不是实际推荐。</p></div></div>
    {plan.shadowSimulated.length ? <div className="table-scroll"><table className="data-table"><thead><tr><th>模拟候选</th><th>方向</th><th>概率</th><th>官方赔率</th><th>预期收益率</th><th>风险</th><th>模拟额度</th><th>未通过原因</th></tr></thead><tbody>{plan.shadowSimulated.map(row => <tr key={row.matchId}><td>{row.match}<br/><code>{row.officialMatchId}</code></td><td>{outcomeLabel[row.outcome]}</td><td>{pct(row.probability)}</td><td>{row.officialSp.toFixed(2)}</td><td style={{color: row.ev <= 0 ? "var(--danger)" : undefined}}>{pct(row.ev)}</td><td>{row.riskLevel}</td><td>¥{row.amount.toFixed(2)}</td><td>{row.reasons.join("；") || "未通过生产硬规则"}</td></tr>)}</tbody></table></div> : <p className="empty-state">当前没有赔率和概率均有效的影子候选。</p>}
  </section>;
}
