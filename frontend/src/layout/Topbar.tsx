import { Bell, CircleHelp, Menu, ShieldCheck } from "lucide-react";
import { Link, NavLink } from "react-router-dom";

const nav = [["总览","/dashboard"],["比赛池","/matches"],["推荐","/recommendations"],["Agent监控","/agents"],["回测","/backtest"],["设置","/settings"]];

export default function Topbar({onMenu,accountName="admin"}:{onMenu:()=>void;accountName?:string}) {
  return <header className="topbar">
    <div className="brand-wrap">
      <button className="mobile-trigger" onClick={onMenu} aria-label="打开菜单"><Menu size={20}/></button>
      <div className="logo"><ShieldCheck size={22}/></div><strong>竞彩多Agent决策平台</strong>
    </div>
    <nav className="topnav">{nav.map(([label,path])=><NavLink key={path} to={path} className={({isActive})=>isActive?"active":""}>{label}</NavLink>)}</nav>
    <div className="top-actions">
      <Link className="icon-btn notification" aria-label="通知" to="/notifications"><Bell size={19}/></Link>
      <a className="icon-btn" aria-label="帮助" href="/docs" target="_blank" rel="noreferrer"><CircleHelp size={19}/></a>
      <span className="avatar">{accountName.slice(0,2).toUpperCase()}</span><span className="admin">{accountName}</span>
    </div>
  </header>
}
