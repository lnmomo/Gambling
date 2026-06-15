import {Navigate, Route, Routes} from "react-router-dom";
import useApi from "./hooks/useApi";
import AppLayout from "./layout/AppLayout";
import AgentMonitorPage from "./pages/AgentMonitorPage";
import AuditLogsPage from "./pages/AuditLogsPage";
import BacktestPage from "./pages/BacktestPage";
import BankrollPage from "./pages/BankrollPage";
import DashboardPage from "./pages/DashboardPage";
import DataCenterPage from "./pages/DataCenterPage";
import LiveMonitorPage from "./pages/LiveMonitorPage";
import MatchDetailPage from "./pages/MatchDetailPage";
import MatchPoolPage from "./pages/MatchPoolPage";
import NotificationsPage from "./pages/NotificationsPage";
import RecommendationPage from "./pages/RecommendationPage";
import RulesPage from "./pages/RulesPage";
import SettingsPage from "./pages/SettingsPage";

function HomeRedirect() { const {data} = useApi("/api/settings", {default_page: "/dashboard"}); return <Navigate to={data.default_page || "/dashboard"} replace/>; }
export default function App() { return <Routes><Route element={<AppLayout/>}><Route path="/dashboard" element={<DashboardPage/>}/><Route path="/matches" element={<MatchPoolPage/>}/><Route path="/matches/:matchId" element={<MatchDetailPage/>}/><Route path="/recommendations" element={<RecommendationPage/>}/><Route path="/live-monitor" element={<LiveMonitorPage/>}/><Route path="/agents" element={<AgentMonitorPage/>}/><Route path="/backtest" element={<BacktestPage/>}/><Route path="/bankroll" element={<BankrollPage/>}/><Route path="/data-center" element={<DataCenterPage/>}/><Route path="/rules" element={<RulesPage/>}/><Route path="/notifications" element={<NotificationsPage/>}/><Route path="/audit-logs" element={<AuditLogsPage/>}/><Route path="/settings" element={<SettingsPage/>}/><Route index element={<HomeRedirect/>}/></Route><Route path="*" element={<Navigate to="/dashboard" replace/>}/></Routes>; }
