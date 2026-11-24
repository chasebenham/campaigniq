import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router"
import { expect, it, vi } from "vitest"

import { App } from "@/app"
import { page, sampleFinding, sampleRun } from "./detection-fixtures"

function mount(path = "/insights") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>)
}

it("runs deterministic detection explicitly and shows and filters persisted findings", async () => {
  let ran = false
  const fetches = vi.fn((input: string, init?: RequestInit) => {
    const url = new URL(input, "http://localhost")
    if (url.pathname.endsWith("/detection/runs") && init?.method === "POST") {
      ran = true
      return Promise.resolve(Response.json(sampleRun, { status: 201 }))
    }
    if (url.pathname.endsWith("/detection/runs")) return Promise.resolve(Response.json(page(ran ? [sampleRun] : [])))
    if (url.pathname.endsWith("/insights/summary")) return Promise.resolve(Response.json({
      run: ran ? sampleRun : null, counts: ran ? { PERFORMANCE_RISK: 1, INSUFFICIENT_EVIDENCE: 2 } : {},
    }))
    if (url.pathname.endsWith("/insights")) return Promise.resolve(Response.json(page(
      ran && !url.searchParams.has("policy_id") ? [sampleFinding] : [],
    )))
    if (url.pathname.endsWith("/campaign-options")) return Promise.resolve(Response.json(page([])))
    throw new Error(`Unexpected request ${input}`)
  })
  vi.stubGlobal("fetch", fetches)
  const user = userEvent.setup()
  mount()
  expect(await screen.findByText("No findings for this selection")).toBeInTheDocument()
  expect(ran).toBe(false)
  await user.click(screen.getByRole("button", { name: "Run Performance Analysis" }))
  const table = await screen.findByRole("table", { name: "Performance findings" })
  expect(within(table).getByRole("link", { name: "CPA deterioration" })).toHaveAttribute("href", "/insights/21")
  expect(within(table).getByText("$30.00 CPA · 25%")).toBeInTheDocument()
  await user.selectOptions(screen.getByLabelText("Policy"), "D-02")
  expect(await screen.findByText("No findings for this selection")).toBeInTheDocument()
  expect(fetches.mock.calls.some(([url]) => url.includes("policy_id=D-02"))).toBe(true)
  expect(fetches.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1)
})

it("shows real evidence periods and links to campaign reporting", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(Response.json(sampleFinding))))
  mount("/insights/21")
  expect(await screen.findByRole("heading", { name: "CPA deterioration" })).toBeInTheDocument()
  expect(screen.getByRole("heading", { name: "Current period" })).toBeInTheDocument()
  expect(screen.getByRole("heading", { name: "Baseline period" })).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "Trail Collection Search" })).toHaveAttribute(
    "href", "/campaigns/2?start_date=2026-11-02&end_date=2026-11-15",
  )
  expect(screen.getByText("Conversion credit is platform-attributed.")).toBeInTheDocument()
})
