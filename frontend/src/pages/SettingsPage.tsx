import {useEffect, useState} from "react";
import {apiPut} from "../api/system";
import EnvironmentStatusPanel from "../components/EnvironmentStatusPanel";
import ModelGovernancePanel from "../components/ModelGovernancePanel";
import PageHeader from "../components/PageHeader";
import RiskLimitTable from "../components/RiskLimitTable";
import {getBankrollConfig} from "../services/bankrollService";
import {fetchSystemHealth, type SystemHealth} from "../services/healthService";
import useApi from "../hooks/useApi";

type Settings={account_name:string;email:string;refresh_seconds:number;default_page:string;recommendation_notifications:boolean;risk_notifications:boolean;compact_table:boolean};

export default function SettingsPage() {
  const {data,setData,loading,error}=useApi<Settings>("/api/settings",{account_name:"admin",email:"",refresh_seconds:60,default_page:"/dashboard",recommendation_notifications:true,risk_notifications:true,compact_table:false});
  const [message,setMessage]=useState(""),[health,setHealth]=useState<SystemHealth|null>(null),bankroll=getBankrollConfig();
  useEffect(()=>{let alive=true;fetchSystemHealth().then(result=>{if(alive)setHealth(result)});return()=>{alive=false}},[]);
  const save=async()=>{try{setData(await apiPut<Settings>("/api/settings",data));setMessage("系统设置已保存")}catch(e){setMessage(e instanceof Error?e.message:"保存失败")}};
  return <div className="page"><PageHeader title="系统设置" subtitle="配置刷新周期、模型治理、资金管理参数和生产环境状态。"/>
    {health&&<EnvironmentStatusPanel health={health}/>}
    <ModelGovernancePanel/>
    <RiskLimitTable config={bankroll}/>
    <section className="panel"><h2>资金管理设置</h2><p>更高 Kelly fraction 会增加波动和回撤风险。默认使用 1/4 Kelly。</p><div className="summary-strip" style={{padding:16,margin:0}}><span>Bankroll<b>{bankroll.currentBankroll}</b></span><span>Base Unit<b>{bankroll.baseUnit}</b></span><span>Staking Mode<b>{bankroll.stakingMode}</b></span><span>Kelly Fraction<b>{(bankroll.kellyFraction*100).toFixed(0)}%</b></span><span>Drawdown Control<b>{bankroll.drawdownControlEnabled?"ON":"OFF"}</b></span><span>Correlation Control<b>{bankroll.correlationControlEnabled?"ON":"OFF"}</b></span></div></section>
    <section className="panel settings-grid">{loading?<p>加载中...</p>:error?<p>{error}</p>:<><label>账户名称<input value={data.account_name} onChange={e=>setData({...data,account_name:e.target.value})}/></label><label>邮箱<input value={data.email} onChange={e=>setData({...data,email:e.target.value})}/></label><label>刷新频率<select value={data.refresh_seconds} onChange={e=>setData({...data,refresh_seconds:Number(e.target.value)})}><option value="30">30 秒</option><option value="60">60 秒</option><option value="300">5 分钟</option></select></label><button className="primary-button" onClick={save}>保存设置</button>{message&&<span className="success-message">{message}</span>}</>}</section>
    <section className="panel"><h2>数据目录说明</h2><p>`data/runtime`、`data/cache`、`data/logs`、`data/raw`、`data/private` 不提交 Git；真实数据库、真实 CSV、API key 也不提交。迁移文件保存在 `football_agents/migrations`。</p></section>
  </div>;
}
