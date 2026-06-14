import {Link, useParams} from "react-router-dom";
import EmptyState from "../components/EmptyState";
import RiskTag from "../components/RiskTag";
import StatusTag from "../components/StatusTag";
import useOfficialMatches from "../hooks/useOfficialMatches";
import type {ThreeWayProbability} from "../types";

const keys = ["home", "draw", "away"] as const;
const labels = {home: "主胜", draw: "平局", away: "客胜"} as const;
const actions = {home: "HOME", draw: "DRAW", away: "AWAY"} as const;
const pct = (value: number) => Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "-";
const odds = (value: number) => Number.isFinite(value) && value > 0 ? value.toFixed(2) : "-";
const tripleRow = (name: string, values: ThreeWayProbability, format: (value: number) => string) =>
  <tr><th>{name}</th>{keys.map(key => <td key={key}>{format(values[key])}</td>)}</tr>;

export default function MatchDetailPage() {
  const {matchId} = useParams();
  const {matches, loading, error} = useOfficialMatches();
  const match = matches.find(item => item.id === matchId);
  if (loading) return <div className="page"><EmptyState title="正在加载官方比赛..." /></div>;
  if (error || !match) return <div className="page"><EmptyState title="比赛不存在或官方数据加载失败" description={error || "请从官方比赛池选择有效比赛"} /><Link className="primary-link" to="/matches">返回比赛池</Link></div>;

  const prediction = match.prediction;
  const available = prediction.probabilityAvailable;
  const diagnostics = prediction.diagnostics;
  return <div className="page detail-page">
    <div className="detail-hero"><div><Link to="/matches">返回比赛池</Link><p>{match.league} · {match.officialMatchId}</p><h1>{match.homeTeam} <em>vs</em> {match.awayTeam}</h1><span>{new Date(match.kickoffTime).toLocaleString("zh-CN")} · 更新于 {new Date(match.updatedAt).toLocaleString("zh-CN")}</span></div><div><StatusTag status={match.status} /><RiskTag level={prediction.riskLevel} /></div></div>
    <div className="detail-layout"><main>
      <section className="probability-grid">{keys.map(key => <article className={`probability-card ${prediction.recommendation === actions[key] ? "selected" : ""}`} key={key}><span>{labels[key]}</span><strong>{available ? pct(prediction.finalProbability[key]) : "不可用"}</strong><dl><div><dt>最终决策公平赔率</dt><dd>{available ? odds(prediction.finalFairOdds[key]) : "-"}</dd></div><div><dt>纯模型公平赔率</dt><dd>{available ? odds(prediction.pureModelFairOdds[key]) : "-"}</dd></div><div><dt>官方 SP</dt><dd>{odds(match.officialSp[key])}</dd></div><div><dt>EV</dt><dd>{available ? pct(prediction.ev[key]) : "-"}</dd></div></dl></article>)}</section>

      <section className="panel tabs-panel"><div className="panel-heading"><div><h2>概率与公平赔率分解</h2><p>官方 SP 是真实采集值；纯模型公平赔率不含市场；最终决策公平赔率融合市场、模型、校准与风控，不是真实市场报价。</p></div></div><div className="table-scroll"><table className="data-table"><thead><tr><th>项目</th><th>主胜</th><th>平局</th><th>客胜</th></tr></thead><tbody>
        {tripleRow("官方 SP", prediction.officialSp, odds)}
        {tripleRow("官方市场去水概率", prediction.marketProbability, pct)}
        {tripleRow("官方市场去水公平赔率", prediction.marketFairOdds, odds)}
        {tripleRow("外部市场共识概率", prediction.externalMarketProbability, pct)}
        {tripleRow("外部市场公平赔率", prediction.externalMarketFairOdds, odds)}
        {tripleRow("纯模型概率", prediction.pureModelProbability, pct)}
        {tripleRow("纯模型公平赔率", prediction.pureModelFairOdds, odds)}
        {tripleRow("最终决策概率", prediction.finalProbability, pct)}
        {tripleRow("最终决策公平赔率", prediction.finalFairOdds, odds)}
        {tripleRow("EV", prediction.ev, pct)}
        {tripleRow("纯模型 Edge", prediction.pureModelEdge, pct)}
        {tripleRow("最终 Edge", prediction.finalEdge, pct)}
      </tbody></table></div></section>

      <section className="panel tabs-panel"><div className="panel-heading"><div><h2>模型组成</h2><p>纯模型概率固定使用 Dixon-Coles 70% + Elo 30%。</p></div></div><div className="table-scroll"><table className="data-table"><thead><tr><th>模型</th><th>主胜</th><th>平局</th><th>客胜</th></tr></thead><tbody>{tripleRow("Dixon-Coles", prediction.dixonColesProbability, pct)}{tripleRow("Elo", prediction.eloProbability, pct)}{tripleRow("纯模型", prediction.pureModelProbability, pct)}{tripleRow("市场锚定后", prediction.anchoredProbability, pct)}</tbody></table></div></section>

      <section className="panel tabs-panel"><div className="panel-heading"><div><h2>外部市场共识</h2><p>外部市场概率先将每家公司赔率转换为隐含概率并去水，再剔除异常值并按博彩公司权重加权平均。</p></div></div><div className="summary-strip" style={{padding: 16, margin: 0}}><span>质量评分<b>{prediction.externalMarketQuality.qualityScore}</b></span><span>质量等级<b>{prediction.externalMarketQuality.qualityLevel}</b></span><span>博彩公司<b>{prediction.externalMarketQuality.bookmakerCount}</b></span><span>有效 / 剔除<b>{prediction.externalMarketQuality.includedBookmakerCount} / {prediction.externalMarketQuality.excludedBookmakerCount}</b></span><span>平均水位<b>{pct(prediction.externalMarketQuality.averageOverround)}</b></span><span>公司最大分歧<b>{pct(prediction.externalMarketQuality.maxBookmakerDeviation)}</b></span><span>官方市场偏离<b>{pct(prediction.externalMarketQuality.officialMarketDeviation.maxDeviation)}</b></span></div><div className="table-scroll"><table className="data-table"><thead><tr><th>博彩公司</th><th>原始主胜</th><th>原始平局</th><th>原始客胜</th><th>去水主胜</th><th>去水平局</th><th>去水客胜</th><th>Overround</th><th>权重</th><th>纳入</th><th>剔除原因</th></tr></thead><tbody>{prediction.normalizedBookmakers.map(book => <tr key={`${book.bookmakerKey ?? book.bookmaker}-${book.lastUpdate}`}><td>{book.bookmaker}</td><td>{odds(book.rawOdds.home)}</td><td>{odds(book.rawOdds.draw)}</td><td>{odds(book.rawOdds.away)}</td><td>{pct(book.normalizedProbability.home)}</td><td>{pct(book.normalizedProbability.draw)}</td><td>{pct(book.normalizedProbability.away)}</td><td>{pct(book.overround)}</td><td>{book.weight.toFixed(2)}</td><td>{book.included ? "是" : "否"}</td><td>{book.exclusionReason ?? "-"}</td></tr>)}</tbody></table></div><div className="critic-list tab-content">{prediction.externalMarketWarnings.map(warning => <div key={warning}>{warning}</div>)}</div></section>

      <section className="panel tabs-panel"><div className="panel-heading"><div><h2>诊断解释</h2><p>解释预测为何被接受、锚定或拦截</p></div></div><div className="summary-strip" style={{padding: 16, margin: 0}}><span>主队历史样本<b>{diagnostics.homeMatchCount}</b></span><span>客队历史样本<b>{diagnostics.awayMatchCount}</b></span><span>联赛历史样本<b>{diagnostics.leagueMatchCount}</b></span><span>市场锚定<b>{diagnostics.marketAnchored ? "已触发" : "未触发"}</b></span></div><div className="critic-list tab-content">{diagnostics.warnings.map(warning => <div key={warning}>{warning}</div>)}</div></section>

      <section className="panel tabs-panel"><div className="panel-heading"><div><h2>Critic 报告</h2><p>{prediction.criticReport.passed ? "推荐成立条件已满足" : "不推荐原因"}</p></div></div><div className="critic-list tab-content">{prediction.criticReport.reasons.map(reason => <div className="fail" key={reason}>{reason}</div>)}{prediction.criticReport.warnings.map(warning => <div key={warning}>{warning}</div>)}{prediction.criticReport.passed && <div>检查通过，最终动作：{prediction.criticReport.finalAction}</div>}</div></section>
    </main><aside className="decision-panel panel"><h2>推荐决策</h2><span className={`decision-result ${prediction.recommendation === "NO_BET" ? "blocked" : ""}`}>{prediction.recommendation}</span>{prediction.recommendation === "NO_BET" && <p>{prediction.criticReport.reasons.join("；") || "不满足推荐条件"}</p>}<dl><div><dt>置信等级</dt><dd>{prediction.confidence}</dd></div><div><dt>建议仓位</dt><dd>¥{prediction.suggestedStake.toFixed(2)} ({(prediction.stakeFraction * 100).toFixed(2)}%)</dd></div><div><dt>最佳 EV</dt><dd>{prediction.recommendedEv === null ? "-" : pct(prediction.recommendedEv)}</dd></div><div><dt>动态阈值</dt><dd>{pct(prediction.dynamicEvThreshold)}</dd></div><div><dt>风险等级</dt><dd>{prediction.riskLevel}</dd></div></dl></aside></div>
  </div>;
}
