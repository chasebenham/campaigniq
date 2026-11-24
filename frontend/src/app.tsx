import {
  BarChart3, ChartNoAxesCombined, Database, FlaskConical, LayoutDashboard,
  Lightbulb, Megaphone, NotebookPen, Sparkles,
} from "lucide-react"
import { Link, NavLink, Outlet, Route, Routes } from "react-router"

import { Overview } from "./pages/overview"
import { CampaignDetail, Campaigns } from "./pages/campaigns"
import { Imports } from "./pages/imports"
import { InsightDetail, Insights } from "./pages/insights"
import { AiAnalyst } from "./pages/ai-analyst"

const navigation = [
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/campaigns", label: "Campaigns", icon: Megaphone },
  { to: "/insights", label: "Insights", icon: Lightbulb },
  { to: "/ai-analyst", label: "AI Analyst", icon: Sparkles },
  { to: "/imports", label: "Data Imports", icon: Database },
]
const upcoming = [
  { label: "Budget Lab", icon: FlaskConical },
  { label: "Strategy Briefs", icon: NotebookPen },
]

function Shell() {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">Skip to content</a>
      <aside className="sidebar">
        <Link to="/" className="brand">
          <span className="brand-icon"><ChartNoAxesCombined size={22} /></span>
          <span>Campaign<span className="brand-accent">IQ</span></span>
        </Link>

        <nav aria-label="Workspace" className="workspace-nav">
          <p className="nav-label">WORKSPACE</p>
          {navigation.map(({ to, label, icon: Icon }) => (
            <NavLink to={to} end={to === "/"} key={to} className="nav-link"><Icon size={18} />{label}</NavLink>
          ))}
          <div className="upcoming">
            <p className="nav-label">COMING SOON</p>
            {upcoming.map(({ label, icon: Icon }) => (
              <div className="nav-link nav-unavailable" key={label}><Icon size={18} />{label}</div>
            ))}
          </div>
        </nav>

        <div className="workspace-account">
          <span className="account-avatar">N</span>
          <span><strong>Northstar Outfitters</strong><small>Fictional brand</small></span>
        </div>
      </aside>

      <div className="app-body">
        <header className="topbar">
          <span><BarChart3 size={16} aria-hidden="true" /> Marketing Analytics</span>
          <span className="topbar-currency">USD reporting</span>
        </header>
        <main id="main" className="main-content" tabIndex={-1}><Outlet /></main>
      </div>
    </div>
  )
}

function NotFound() {
  return <section className="page-heading"><h1>Page unavailable</h1><Link className="text-link" to="/">Go to Overview</Link></section>
}

export function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Overview />} />
        <Route path="campaigns" element={<Campaigns />} />
        <Route path="campaigns/:campaignId" element={<CampaignDetail />} />
        <Route path="imports" element={<Imports />} />
        <Route path="insights" element={<Insights />} />
        <Route path="insights/:findingId" element={<InsightDetail />} />
        <Route path="ai-analyst" element={<AiAnalyst />} />
        <Route path="ai-analyst/:findingId" element={<AiAnalyst />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
