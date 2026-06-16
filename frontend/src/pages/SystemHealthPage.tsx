import {useEffect, useState} from "react";
import DataQualityPanel from "../components/DataQualityPanel";
import EnvironmentStatusPanel from "../components/EnvironmentStatusPanel";
import PageHeader from "../components/PageHeader";
import SchedulerStatusPanel from "../components/SchedulerStatusPanel";
import SystemHealthPanel from "../components/SystemHealthPanel";
import {fetchSystemHealth, type SystemHealth} from "../services/healthService";

export default function SystemHealthPage() {
  const [health,setHealth]=useState<SystemHealth|null>(null),[loading,setLoading]=useState(true);
  useEffect(()=>{let alive=true;fetchSystemHealth().then(data=>{if(alive)setHealth(data)}).finally(()=>{if(alive)setLoading(false)});return()=>{alive=false}},[]);
  if(loading) return <div className="page"><PageHeader title="系统健康" subtitle="正在读取 /health..."/></div>;
  if(!health) return <div className="page"><PageHeader title="系统健康" subtitle="健康检查不可用"/></div>;
  return <div className="page"><PageHeader title="系统健康" subtitle="数据库、同步、任务、模型和环境配置状态。"/>
    <SystemHealthPanel health={health}/>
    <div className="two-column"><EnvironmentStatusPanel health={health}/><DataQualityPanel health={health}/></div>
    <SchedulerStatusPanel health={health}/>
  </div>;
}
