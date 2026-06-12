import { useState } from "react";
import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import Topbar from "./Topbar";
import useApi from "../hooks/useApi";

export default function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const {data:settings}=useApi("/api/settings",{account_name:"admin",compact_table:false});
  return (
    <div className={`app-shell ${settings.compact_table?"compact-mode":""}`}>
      <Topbar accountName={settings.account_name} onMenu={() => setSidebarOpen(value => !value)} />
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <main className="app-content"><Outlet /></main>
      {sidebarOpen && <button className="sidebar-mask" aria-label="关闭菜单" onClick={() => setSidebarOpen(false)} />}
    </div>
  );
}
