import {Activity, BellRing, BookOpenCheck, Bot, ChartNoAxesCombined, CircleDollarSign, Database, HeartPulse, LayoutDashboard, ListChecks, RadioTower, ScrollText} from "lucide-react";
import {NavLink} from "react-router-dom";

const menus = [
  [LayoutDashboard, "总览", "/dashboard"],
  [ListChecks, "比赛池", "/matches"],
  [BookOpenCheck, "推荐", "/recommendations"],
  [RadioTower, "实时监控", "/live-monitor"],
  [Bot, "Agent 监控", "/agents"],
  [ChartNoAxesCombined, "回测分析", "/backtest"],
  [CircleDollarSign, "资金与盈亏", "/bankroll"],
  [Database, "数据中心", "/data-center"],
  [Activity, "规则与策略", "/rules"],
  [HeartPulse, "系统健康", "/system-health"],
  [BellRing, "通知中心", "/notifications"],
  [ScrollText, "日志审计", "/audit-logs"],
] as const;

export default function Sidebar({open,onClose}:{open:boolean;onClose:()=>void}) {
  return <aside className={`sidebar ${open?"open":""}`}>
    <div className="sidebar-heading">业务工作台</div>
    <nav>{menus.map(([Icon,label,path])=><NavLink key={path} to={path} onClick={onClose} className={({isActive})=>isActive?"active":""}><Icon size={18}/><span>{label}</span></NavLink>)}</nav>
    <div className="system-health"><div><span className="status-dot"/><b>治理健康已接入</b></div><p>数据、任务与审计状态可追踪</p><div className="health-line"><i/></div><small>以 /health 接口状态为准</small></div>
  </aside>;
}
