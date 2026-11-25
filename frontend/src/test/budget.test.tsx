import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router"
import { expect, it, vi } from "vitest"

import { App } from "@/app"
import type { Benchmark, Calculation, Defaults, Plan, SavedScenario } from "@/lib/budget"
import { page, sampleFinding } from "./detection-fixtures"

const settings: Defaults = {
  reference: { start: "2026-09-01", end: "2026-09-28" },
  planning: { start: "2026-11-01", end: "2026-11-30" },
  mature_through: "2026-10-15", earliest_planning_date: "2026-10-23",
  minimum_observed_days: 14, maturation_days: 7, max_campaigns: 20,
  assumptions: {
    conservative: { cpa_change_pct: "15", marginal_cpa_change_pct: "30", value_per_purchase_change_pct: "-5" },
    base: { cpa_change_pct: "0", marginal_cpa_change_pct: "15", value_per_purchase_change_pct: "0" },
    optimistic: { cpa_change_pct: "-5", marginal_cpa_change_pct: "5", value_per_purchase_change_pct: "3" },
  },
}
const rows: Benchmark[] = [{
  campaign_id: sampleFinding.campaign_id, campaign_name: "Trail Search", platform: "GOOGLE_ADS", eligible: true,
  blockers: [], flags: [], attribution_contexts: sampleFinding.reporting_context,
  average_daily_spend: "10.00", peak_daily_spend: "12.50", period: sampleFinding.current_evidence,
}, {
  campaign_id: 8, campaign_name: "Outdoor Lifestyle", platform: "META_ADS", eligible: true, blockers: [],
  flags: [], attribution_contexts: sampleFinding.reporting_context, average_daily_spend: "15.00",
  peak_daily_spend: "20.00", period: sampleFinding.current_evidence,
}]
const outcome = { spend: "500", purchases: "25.23", value: "806.21", cpa: "19.82", roas: "1.61" } as const
const base = { portfolio: outcome, delta: outcome, versus_base: outcome, campaigns: [] }
const result: Calculation = {
  model_version: "1.0.0", evidence_fingerprint: "a".repeat(64), reference_days: 28, planning_days: 30,
  minimum_observed_days: 14, maturation_days: 7, benchmarks: rows, allocation: [],
  observed: outcome, normalized: outcome, scenarios: {
    base, conservative: { ...base, portfolio: { ...outcome, value: "623.12" } },
    optimistic: { ...base, portfolio: { ...outcome, purchases: "30.15", value: "950.00" } },
  },
  warnings: [{
    code: "EXTRAPOLATION_SUBSTANTIAL", severity: "warning", campaign_id: rows[0].campaign_id,
    scenario: null, message: "Substantial extrapolation. Planned spend is above the observed range.",
  }],
}

function mount(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>)
}

function fixture() {
  let saved: SavedScenario | undefined
  const fetches = vi.fn(async (input: string, init?: RequestInit) => {
    const url = new URL(input, "http://localhost")
    const method = init?.method ?? "GET"
    const path = url.pathname
    if (path.endsWith("/assumptions")) return Response.json(settings)
    if (path.endsWith("/eligible-campaigns")) {
      const id = url.searchParams.get("campaign_id")
      return Response.json(page(rows.filter(item => !id || String(item.campaign_id) === id)))
    }
    if (path.endsWith("/allocations") && method === "POST") return Response.json([
      { campaign_id: rows[0].campaign_id, dollars: "200.00", percent: "40.00" },
      { campaign_id: rows[1].campaign_id, dollars: "300.00", percent: "60.00" },
    ])
    if (path.endsWith("/calculate") && method === "POST") return Response.json(result)
    if (path.endsWith("/scenarios") && method === "POST") {
      const { plan } = JSON.parse(String(init?.body)) as { plan: Plan }
      saved = {
        id: 5, name: plan.name, reference: plan.reference, planning: plan.planning, total_budget: "500.00",
        created_at: "2026-10-16T13:04:00Z", updated_at: "2026-10-16T13:04:00Z", calculated_at: "2026-10-16T13:04:00Z",
        model_version: result.model_version, evidence_fingerprint: result.evidence_fingerprint,
        status: "CURRENT", cloned_from_id: null, plan, result,
      }
      return Response.json(saved, { status: 201 })
    }
    if (path.endsWith("/scenarios/5") && saved) return Response.json(saved)
    if (path.endsWith("/scenarios")) return Response.json(page(saved ? [saved] : []))
    if (path.includes("/insights/")) return Response.json(sampleFinding)
    throw new Error(`Unexpected request ${input}`)
  })
  vi.stubGlobal("fetch", fetches)
  return fetches
}

it("selects campaigns, validates allocations, restores historical proportions and saves a reviewed model", async () => {
  const requests = fixture()
  const user = userEvent.setup()
  const screenView = mount("/budget-lab")
  const trail = await screen.findByRole("checkbox", { name: /Trail Search/ })
  const outdoor = screen.getByRole("checkbox", { name: /Outdoor Lifestyle/ })
  const calculate = screen.getByRole("button", { name: "Calculate scenarios" })
  expect(calculate).toBeDisabled()
  expect(calculate).toHaveAccessibleDescription(/Enter a total budget in USD.*Select at least two eligible campaigns/)
  await user.click(trail)
  await user.click(outdoor)
  const budget = screen.getByLabelText("Total budget (USD)")
  fireEvent.change(budget, { target: { value: "-300" } })
  expect(screen.getByRole("alert")).toHaveTextContent("Enter a USD amount")
  fireEvent.change(budget, { target: { value: "500" } })
  fireEvent.change(screen.getByLabelText("Scenario name"), { target: { value: "Fall sensitivity plan" } })
  const trailAmount = screen.getByRole("textbox", { name: "Trail Search allocation" })
  fireEvent.change(trailAmount, { target: { value: "300.55" } })
  expect(screen.getByText("Remaining · $199.45")).toBeInTheDocument()
  expect(calculate).toHaveAccessibleDescription(/Dollar allocations must match the total budget\. Allocate \$199\.45/)
  await user.click(screen.getByRole("button", { name: "Balance with Outdoor Lifestyle" }))
  expect(screen.getByRole("textbox", { name: "Outdoor Lifestyle allocation" })).toHaveValue("199.45")
  expect(screen.getByText("Remaining · $0.00")).toBeInTheDocument()
  expect(calculate).toBeEnabled()
  expect(screen.getByRole("button", { name: "Save scenario" })).toHaveAccessibleDescription(/Calculate scenarios before saving/)
  await user.click(screen.getByRole("button", { name: "Restore historical allocation" }))
  await waitFor(() => expect(trailAmount).toHaveValue("200.00"))
  expect(requests.mock.calls.find(([url]) => url.endsWith("/allocations"))?.[1]?.body).toContain('"method":"historical"')

  await user.selectOptions(screen.getByLabelText("Assumption case"), "optimistic")
  const change = screen.getByLabelText(/Base CPA change/)
  fireEvent.change(change, { target: { value: "-100" } })
  expect(calculate).toBeDisabled()
  expect(calculate).toHaveAccessibleDescription(/In the Optimistic case, enter a value from -90% to 300% for Base CPA change/)
  fireEvent.change(change, { target: { value: "-8" } })
  await user.click(screen.getByRole("button", { name: "Calculate scenarios" }))
  expect(await screen.findByText(/Substantial extrapolation/)).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: /Optimistic/ }))
  const modeled = screen.getByRole("table", { name: "Optimistic portfolio results" })
  expect(within(modeled).getByText("30.15")).toBeInTheDocument()
  expect(screen.getByText("-8%")).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "Save scenario" }))
  expect(await screen.findByRole("heading", { name: "Fall sensitivity plan" })).toBeInTheDocument()
  screenView.unmount()

  mount("/budget-lab")
  await user.click(await screen.findByRole("link", { name: "Fall sensitivity plan" }))
  expect(await screen.findByRole("heading", { name: "Fall sensitivity plan" })).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: /Optimistic/ }))
  expect(screen.getByText("-8%")).toBeInTheDocument()
  expect(requests.mock.calls.filter(([url]) => url.endsWith("/calculate"))).toHaveLength(1)
  expect(requests.mock.calls.every(([url]) => !url.includes("/ai/"))).toBe(true)
})

it("opens a finding-context draft with the linked campaign selected and requires a deliberate allocation", async () => {
  const requests = fixture()
  const user = userEvent.setup()
  mount(`/insights/${sampleFinding.id}`)
  await user.click(await screen.findByRole("link", { name: "Model a budget scenario" }))
  expect(await screen.findByRole("checkbox", { name: /Trail Search/ })).toBeChecked()
  expect(screen.getByRole("link", { name: `Finding #${sampleFinding.id}` })).toHaveAttribute("href", `/insights/${sampleFinding.id}`)
  expect(screen.getByRole("textbox", { name: "Trail Search allocation" })).toHaveValue("0")
  expect(screen.getByRole("button", { name: "Calculate scenarios" })).toBeDisabled()
  expect(requests.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})
