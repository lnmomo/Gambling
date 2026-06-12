import EmptyState from "../components/EmptyState";
import PageHeader from "../components/PageHeader";
import useOfficialMatches from "../hooks/useOfficialMatches";

export default function RecommendationPage(){
  const {matches,loading,error}=useOfficialMatches();
  return <div className="page"><PageHeader title="推荐中心" subtitle="只展示后端真实模型决策，不根据官方 SP 伪造推荐"/><section className="panel">{loading?<p className="empty-state">正在检查推荐数据...</p>:error?<p className="empty-state">{error}</p>:<EmptyState title="暂无真实推荐数据" description={`已接入 ${matches.length} 场官方比赛，但尚未接入真实球队特征和外部市场赔率，因此不生成预测，全部保持 No Bet。`}/>}</section></div>;
}

