import {useMemo,useState} from "react";
import {Link} from "react-router-dom";
import {Activity,CalendarDays,CircleGauge,TrendingUp} from "lucide-react";
import FilterBar from "../components/FilterBar";
import MatchTable from "../components/MatchTable";
import MetricCard from "../components/MetricCard";
import useOfficialMatches from "../hooks/useOfficialMatches";

export default function DashboardPage(){
  const {matches,loading,error}=useOfficialMatches();
  const [search,setSearch]=useState("");const [league,setLeague]=useState("");const [status,setStatus]=useState("");
  const filtered=useMemo(()=>matches.filter(m=>(!search||`${m.homeTeam}${m.awayTeam}`.includes(search))&&(!league||m.league===league)&&(!status||m.status===status)).slice(0,10),[matches,search,league,status]);
  const completeSp=matches.filter(m=>Object.values(m.officialSp).every(Boolean)).length;
  const predictions=matches.filter(m=>m.predictionType).length;
  const calibrated=matches.filter(m=>m.marketCalibrated).length;
  return <div className="page"><div className="page-heading"><div><p>工作台 / 总览</p><h1>总览 Dashboard</h1><span>中国竞彩网官方比赛池实时数据</span></div><div className="sync-state"><span className="status-dot"/>{error?"官方数据连接失败":loading?"正在读取官方数据":"官方数据已同步"}</div></div><section className="metric-grid"><MetricCard title="官方比赛数" value={`${matches.length} 场`} note="来自后端官方比赛池" icon={CalendarDays}/><MetricCard title="完整 SP 场次" value={`${completeSp} 场`} note="胜平负 SP 均完整" icon={TrendingUp} tone="blue"/><MetricCard title="模型预测" value={`${predictions} 场`} note="Elo + Poisson 基线" icon={Activity} tone="purple"/><MetricCard title="市场校准" value={`${calibrated} 场`} note="需完整外部赔率" icon={CircleGauge} tone="orange"/></section><div className="dashboard-layout"><div className="dashboard-main"><section className="panel"><div className="panel-heading"><div><h2>官方比赛池</h2><p>{loading?"加载中":error?error:`共 ${matches.length} 场比赛`}</p></div><Link to="/matches">查看全部</Link></div><FilterBar><input placeholder="搜索球队" value={search} onChange={e=>setSearch(e.target.value)}/><select value={league} onChange={e=>setLeague(e.target.value)}><option value="">全部联赛</option>{[...new Set(matches.map(m=>m.league))].map(x=><option key={x}>{x}</option>)}</select><select value={status} onChange={e=>setStatus(e.target.value)}><option value="">全部状态</option><option value="NOT_STARTED">未开赛</option><option value="LIVE">进行中</option><option value="FINISHED">已结束</option></select></FilterBar><MatchTable matches={filtered}/></section><section className="panel"><div className="panel-heading"><div><h2>推荐状态</h2><p>官方数据与模型结果严格分离</p></div></div><p className="empty-state">官方比赛尚缺真实球队 Elo、预期进球和外部市场赔率，因此不生成模型概率、模型赔率或 EV，保持 No Bet。</p></section></div><aside className="dashboard-aside"><section className="panel"><div className="panel-heading"><div><h2>风险预警</h2><p>尚未接入真实风险事件</p></div></div><p className="empty-state">暂无真实风险预警</p></section><section className="panel"><div className="panel-heading"><div><h2>Agent 状态</h2><p>尚未接入运行遥测</p></div><Link to="/agents">查看监控</Link></div><p className="empty-state">暂无真实 Agent 状态</p></section></aside></div></div>;
}

