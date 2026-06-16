import {useEffect, useMemo, useState} from "react";
import {Link} from "react-router-dom";
import {Activity, CalendarDays, CircleGauge, TrendingUp} from "lucide-react";
import BankrollSummaryCard from "../components/BankrollSummaryCard";
import FilterBar from "../components/FilterBar";
import MatchTable from "../components/MatchTable";
import MetricCard from "../components/MetricCard";
import PortfolioExposurePanel from "../components/PortfolioExposurePanel";
import SystemHealthPanel from "../components/SystemHealthPanel";
import {evaluateModelPromotion} from "../algorithm/modelGovernance";
import {calculateDrawdownState} from "../algorithm/drawdownControl";
import {challengerModel, championModel} from "../data/mockModelRegistry";
import {getBankrollConfig, listBankrollTransactions} from "../services/bankrollService";
import {fetchSystemHealth, type SystemHealth} from "../services/healthService";
import {getPortfolioExposure} from "../services/portfolioRiskService";
import useOfficialMatches from "../hooks/useOfficialMatches";

export default function DashboardPage() {
  const {matches,loading,error}=useOfficialMatches();
  const [search,setSearch]=useState(""),[league,setLeague]=useState(""),[status,setStatus]=useState("");
  const [health,setHealth]=useState<SystemHealth|null>(null);
  useEffect(()=>{let alive=true;fetchSystemHealth().then(data=>{if(alive)setHealth(data)});return()=>{alive=false}},[]);

  const filtered=useMemo(()=>matches.filter(match=>(!search||`${match.homeTeam}${match.awayTeam}`.includes(search))&&(!league||match.league===league)&&(!status||match.status===status)).slice(0,10),[matches,search,league,status]);
  const config=getBankrollConfig(),predictions=matches.map(match=>match.prediction),exposure=getPortfolioExposure(predictions),drawdown=calculateDrawdownState(listBankrollTransactions(),config);
  const analyzable=matches.filter(match=>["NOT_STARTED","LIVE"].includes(match.status)),recommendations=matches.filter(match=>match.recommendation!=="NO_BET");
  const averageEv=recommendations.length?recommendations.reduce((sum,match)=>sum+(match.prediction.recommendedEv??0),0)/recommendations.length:0;
  const highRisk=matches.filter(match=>match.riskLevel==="HIGH").length,governance=evaluateModelPromotion(challengerModel,championModel);
  const active=matches.filter(match=>match.prediction.lifecycleStatus==="ACTIVE").length,blocked=matches.filter(match=>match.prediction.stakeRecommendation?.status==="STAKE_BLOCKED").length,reduced=matches.filter(match=>match.prediction.stakeRecommendation?.status==="STAKE_REDUCED").length;

  return <div className="page">
    <div className="page-heading"><div><p>工作台 / 总览</p><h1>概率决策总览</h1><span>官方比赛池驱动，可解释、可回测，默认 NO_BET。</span></div><div className="sync-state"><span className="status-dot"/>{error?"官方数据连接失败":loading?"正在读取官方数据":"官方数据已同步"}</div></div>
    {health&&<SystemHealthPanel health={health} compact/>}
    <section className="metric-grid"><MetricCard title="当前可分析比赛" value={`${analyzable.length} 场`} note="当前及未来比赛" icon={CalendarDays}/><MetricCard title="ACTIVE 推荐" value={`${active} 场`} note={`Stake reduced ${reduced} / blocked ${blocked}`} icon={Activity} tone="blue"/><MetricCard title="推荐平均 EV" value={`${averageEv>=0?"+":""}${(averageEv*100).toFixed(2)}%`} note="EV 使用最终概率和官方 SP" icon={TrendingUp} tone="purple"/><MetricCard title="组合风险" value={drawdown.riskMode} note={`今日暴露 ${(exposure.totalStakePct*100).toFixed(2)}%`} icon={CircleGauge} tone="orange"/></section>
    <BankrollSummaryCard config={config} exposure={exposure} drawdown={drawdown}/>
    <section className="summary-strip"><span>最大单场 stake<b>{exposure.maxSingleBetStake.toFixed(2)}</b></span><span>最大联赛暴露<b>{(Math.max(0,...exposure.exposureByLeague.map(row=>row.stakePct))*100).toFixed(2)}%</b></span><span>高风险比赛<b>{highRisk}</b></span><span>Champion<b>{championModel.version}</b></span><span>治理结论<b>{governance.decision}</b></span><span><Link to="/live-monitor">打开实时监控</Link></span></section>
    <PortfolioExposurePanel exposure={exposure}/>
    <section className="panel"><div className="panel-heading"><div><h2>当前及未来官方比赛池</h2><p>{loading?"加载中...":error?error:`共 ${matches.length} 场比赛`}</p></div><Link to="/matches">查看全部</Link></div><FilterBar><input placeholder="搜索球队" value={search} onChange={event=>setSearch(event.target.value)}/><select value={league} onChange={event=>setLeague(event.target.value)}><option value="">全部联赛</option>{[...new Set(matches.map(match=>match.league))].map(value=><option key={value}>{value}</option>)}</select><select value={status} onChange={event=>setStatus(event.target.value)}><option value="">全部状态</option><option value="NOT_STARTED">未开赛</option><option value="LIVE">进行中</option><option value="FINISHED">已结束</option></select></FilterBar><MatchTable matches={filtered}/></section>
  </div>;
}
