import {useMemo, useState} from "react";
import {Link} from "react-router-dom";
import {Activity, CalendarDays, CircleGauge, TrendingUp} from "lucide-react";
import FilterBar from "../components/FilterBar";
import MatchTable from "../components/MatchTable";
import MetricCard from "../components/MetricCard";
import useOfficialMatches from "../hooks/useOfficialMatches";

export default function DashboardPage() {
  const {matches, loading, error} = useOfficialMatches();
  const [search, setSearch] = useState(""), [league, setLeague] = useState(""), [status, setStatus] = useState("");
  const filtered = useMemo(() => matches.filter(match => (!search || `${match.homeTeam}${match.awayTeam}`.includes(search)) && (!league || match.league === league) && (!status || match.status === status)).slice(0, 10), [matches, search, league, status]);
  const analyzable = matches.filter(match => ["NOT_STARTED", "LIVE"].includes(match.status));
  const recommendations = matches.filter(match => match.recommendation !== "NO_BET");
  const averageEv = recommendations.length ? recommendations.reduce((sum, match) => sum + (match.prediction.recommendedEv ?? 0), 0) / recommendations.length : 0;
  const highRisk = matches.filter(match => match.riskLevel === "HIGH").length;
  return <div className="page"><div className="page-heading"><div><p>工作台 / 总览</p><h1>概率决策总览</h1><span>官方比赛池驱动，可解释、可回测、默认 NO_BET</span></div><div className="sync-state"><span className="status-dot" />{error ? "官方数据连接失败" : loading ? "正在读取官方数据" : "官方数据已同步"}</div></div><section className="metric-grid"><MetricCard title="今日可分析比赛" value={`${analyzable.length} 场`} note="未开赛或进行中" icon={CalendarDays} /><MetricCard title="已推荐场次" value={`${recommendations.length} 场`} note="全部经过 Critic" icon={Activity} tone="blue" /><MetricCard title="推荐平均 EV" value={`${averageEv >= 0 ? "+" : ""}${(averageEv * 100).toFixed(2)}%`} note="无推荐时为 0" icon={TrendingUp} tone="purple" /><MetricCard title="综合风险" value={highRisk ? "HIGH" : matches.some(match => match.riskLevel === "MEDIUM") ? "MEDIUM" : "LOW"} note={`高风险 ${highRisk} 场`} icon={CircleGauge} tone="orange" /></section><section className="panel"><div className="panel-heading"><div><h2>今日官方比赛池</h2><p>{loading ? "加载中" : error ? error : `共 ${matches.length} 场比赛`}</p></div><Link to="/matches">查看全部</Link></div><FilterBar><input placeholder="搜索球队" value={search} onChange={event => setSearch(event.target.value)} /><select value={league} onChange={event => setLeague(event.target.value)}><option value="">全部联赛</option>{[...new Set(matches.map(match => match.league))].map(value => <option key={value}>{value}</option>)}</select><select value={status} onChange={event => setStatus(event.target.value)}><option value="">全部状态</option><option value="NOT_STARTED">未开赛</option><option value="LIVE">进行中</option><option value="FINISHED">已结束</option></select></FilterBar><MatchTable matches={filtered} /></section></div>;
}
