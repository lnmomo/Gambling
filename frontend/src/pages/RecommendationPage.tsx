import {useMemo, useState} from "react";
import {Link} from "react-router-dom";
import FilterBar from "../components/FilterBar";
import PageHeader from "../components/PageHeader";
import useOfficialMatches from "../hooks/useOfficialMatches";

const triple = (values: {home: number; draw: number; away: number}, percent = false) =>
  [values.home, values.draw, values.away].map(value => percent ? `${(value * 100).toFixed(1)}%` : value.toFixed(2)).join(" / ");

export default function RecommendationPage() {
  const {matches, loading, error} = useOfficialMatches();
  const [includeNoBet, setIncludeNoBet] = useState(true);
  const filtered = useMemo(() => matches.filter(match => includeNoBet || match.recommendation !== "NO_BET"), [matches, includeNoBet]);
  return <div className="page"><PageHeader title="推荐中心" subtitle="EV = 最终决策概率 × 官方 SP - 1；纯模型概率只用于解释与方向保护" /><section className="summary-strip"><span>全部比赛<b>{matches.length}</b></span><span>可执行推荐<b>{matches.filter(match => match.recommendation !== "NO_BET").length}</b></span><span>NO_BET<b>{matches.filter(match => match.recommendation === "NO_BET").length}</b></span></section><section className="panel"><FilterBar><label><input type="checkbox" checked={includeNoBet} onChange={event => setIncludeNoBet(event.target.checked)} /> 包含 NO_BET</label></FilterBar>{loading ? <p className="empty-state">正在计算...</p> : error ? <p className="empty-state">{error}</p> : <div className="table-scroll"><table className="data-table"><thead><tr><th>比赛</th><th>官方 SP</th><th>外部市场质量</th><th>外部共识公平赔率</th><th>官方偏离</th><th>纯模型公平赔率</th><th>最终决策公平赔率</th><th>EV</th><th>推荐结论</th><th>外部市场提示</th><th>操作</th></tr></thead><tbody>{filtered.map(match => { const available = match.prediction.probabilityAvailable, quality = match.prediction.externalMarketQuality; return <tr key={match.id}><td><b>{match.homeTeam} vs {match.awayTeam}</b><br/><code>{match.officialMatchId}</code></td><td>{Object.values(match.officialSp).every(value => value > 1) ? triple(match.officialSp) : "不可用"}</td><td><span className={`recommend-badge ${["LOW", "UNAVAILABLE"].includes(quality.qualityLevel) ? "no-bet" : ""}`}>{quality.qualityLevel} / {quality.qualityScore}</span></td><td>{available ? triple(match.prediction.externalMarketFairOdds) : "不可用"}</td><td>{(quality.officialMarketDeviation.maxDeviation * 100).toFixed(1)}%</td><td>{available ? triple(match.prediction.pureModelFairOdds) : "不可用"}</td><td>{available ? triple(match.prediction.finalFairOdds) : "不可用"}</td><td>{available ? triple(match.prediction.ev, true) : "不可用"}</td><td><span className={`recommend-badge ${match.recommendation === "NO_BET" ? "no-bet" : ""}`}>{match.recommendation}</span></td><td title={match.prediction.externalMarketWarnings.join("；")}>{match.prediction.externalMarketWarnings[0] ?? "正常"}</td><td><Link className="table-action" to={`/matches/${match.id}`}>查看详情</Link></td></tr>})}</tbody></table></div>}</section></div>;
}
