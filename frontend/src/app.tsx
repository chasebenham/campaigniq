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
import { BudgetLab } from "./pages/budget-lab"
import { BriefBuilder } from "./pages/brief-builder"
import { SavedBrief, StrategyBriefs } from "./pages/briefs"

const navigation = [
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/campaigns", label: "Campaigns", icon: Megaphone },
  { to: "/insights", label: "Insights", icon: Lightbulb },
  { to: "/ai-analyst", label: "AI Analyst", icon: Sparkles },
  { to: "/budget-lab", label: "Budget Lab", icon: FlaskConical },
  { to: "/strategy-briefs", label: "Strategy Briefs", icon: NotebookPen },
  { to: "/imports", label: "Data Imports", icon: Database },
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
        <Route path="budget-lab" element={<BudgetLab />} />
        <Route path="budget-lab/:scenarioId" element={<BudgetLab />} />
        <Route path="strategy-briefs" element={<StrategyBriefs />} />
        <Route path="strategy-briefs/new" element={<BriefBuilder />} />
        <Route path="strategy-briefs/:briefId/edit" element={<BriefBuilder />} />
        <Route path="strategy-briefs/:briefId" element={<SavedBrief />} />
        <Route path="strategy-briefs/:briefId/versions/:version" element={<SavedBrief />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
