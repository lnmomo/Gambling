import {useMemo,useState} from "react";
import FilterBar from "../components/FilterBar";
import MatchTable from "../components/MatchTable";
import PageHeader from "../components/PageHeader";
import useOfficialMatches from "../hooks/useOfficialMatches";

export default function MatchPoolPage(){
  const {matches,loading,error}=useOfficialMatches();
  const [q,setQ]=useState("");const [league,setLeague]=useState("");const [status,setStatus]=useState("");
  const list=useMemo(()=>matches.filter(m=>(!q||`${m.officialMatchId}${m.league}${m.homeTeam}${m.awayTeam}`.toLowerCase().includes(q.toLowerCase()))&&(!league||m.league===league)&&(!status||m.status===status)),[matches,q,league,status]);
  const count=(statuses:string[])=>matches.filter(m=>statuses.includes(m.status)).length;
  return <div className="page"><PageHeader title="官方比赛池" subtitle="数据来自中国竞彩网公开赛事页面，所有详情均从此进入"/><div className="summary-strip"><span>全部<b>{matches.length}</b></span><span>未开赛<b>{count(["NOT_STARTED"])}</b></span><span>进行中<b>{count(["LIVE"])}</b></span><span>已结束<b>{count(["FINISHED"])}</b></span><span>停售/延期<b>{count(["CLOSED","POSTPONED","CANCELLED"])}</b></span></div><section className="panel"><FilterBar><input placeholder="搜索球队、联赛、比赛ID" value={q} onChange={e=>setQ(e.target.value)}/><select value={league} onChange={e=>setLeague(e.target.value)}><option value="">全部联赛</option>{[...new Set(matches.map(m=>m.league))].map(x=><option key={x}>{x}</option>)}</select><select value={status} onChange={e=>setStatus(e.target.value)}><option value="">全部状态</option>{["NOT_STARTED","LIVE","FINISHED","CLOSED","POSTPONED"].map(x=><option key={x} value={x}>{x}</option>)}</select></FilterBar>{loading?<p className="empty-state">正在加载官方比赛数据...</p>:error?<p className="empty-state">{error}</p>:<MatchTable matches={list}/>}</section></div>;
}
