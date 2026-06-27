import BankrollSummaryCard from "../components/BankrollSummaryCard";
import DrawdownWarningPanel from "../components/DrawdownWarningPanel";
import EmptyState from "../components/EmptyState";
import PageHeader from "../components/PageHeader";
import PortfolioExposurePanel from "../components/PortfolioExposurePanel";
import RiskLimitTable from "../components/RiskLimitTable";
import {calculateDrawdownState} from "../algorithm/drawdownControl";
import {getBankrollConfig,listBankrollTransactions} from "../services/bankrollService";
import {getPortfolioExposure} from "../services/portfolioRiskService";
import useOfficialMatches from "../hooks/useOfficialMatches";
import DailyAllocationPanel from "../components/DailyAllocationPanel";
export default function BankrollPage(){const {matches}=useOfficialMatches(),config=getBankrollConfig(),predictions=matches.map(match=>match.prediction),exposure=getPortfolioExposure(predictions),drawdown=calculateDrawdownState(listBankrollTransactions(),config),recommendations=matches.filter(match=>match.prediction.stakeRecommendation&&match.prediction.stakeRecommendation.status!=="NO_BET");return <div className="page"><PageHeader title="资金与组合风险" subtitle="Risk Adjusted Kelly、组合暴露、回撤控制和额度解释。"/><BankrollSummaryCard config={config} exposure={exposure} drawdown={drawdown}/><DailyAllocationPanel matches={matches}/><div className="two-column"><RiskLimitTable config={config}/><DrawdownWarningPanel drawdown={drawdown}/></div><PortfolioExposurePanel exposure={exposure}/><section className="panel"><div className="panel-heading"><div><h2>当前算法建议额度</h2><p>NO_BET 与 STAKE_BLOCKED 均不会作为有效下注建议。</p></div></div>{recommendations.length?<div className="table-scroll"><table className="data-table"><thead><tr><th>比赛</th><th>推荐</th><th>EV</th><th>Final Stake</th><th>Status</th><th>Capped By</th></tr></thead><tbody>{recommendations.map(match=>{const stake=match.prediction.stakeRecommendation!;return <tr key={match.id}><td>{match.homeTeam} vs {match.awayTeam}</td><td>{match.recommendation}</td><td>{(stake.ev*100).toFixed(2)}%</td><td>{stake.finalStake.toFixed(2)} ({(stake.stakePctOfBankroll*100).toFixed(2)}%)</td><td>{stake.status}</td><td>{stake.cappedBy}</td></tr>})}</tbody></table></div>:<EmptyState title="暂无可执行额度" description="所有比赛当前均为 NO_BET 或被资金风控阻断。"/>}</section></div>}
