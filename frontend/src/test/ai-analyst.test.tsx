import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router"
import { expect, it, vi } from "vitest"

import { App } from "@/app"
import type { Analysis } from "@/lib/ai"
import { page, sampleFinding } from "./detection-fixtures"

const completed: Analysis = {
  id: 55, finding_id: 21, model: "mock-model", prompt_version: "1.0.0", schema_version: "1.0.0",
  status: "COMPLETED", is_current: true, created_at: "2026-11-23T18:31:00Z", finished_at: "2026-11-23T18:31:04Z",
  provider_usage: null, error_message: null,
  evidence_references: [{ path: "current.metrics.cpa", value: "30" }],
  structured_output: {
    finding_id: 21, executive_summary: "Acquisition costs increased.", business_impact_assessment: "Efficiency could weaken.",
    evidence_references: ["current.metrics.cpa"], possible_explanations: ["Traffic mix may have changed."],
    missing_information: ["Device breakdown."], recommended_action_type: "TEST", recommended_action: "Run a controlled test.",
    experiment_hypothesis: "Changing one audience rule may improve efficiency.",
    proposed_experiment: { design: "Keep one comparison cell unchanged.", audience_or_scope: "Eligible prospecting traffic.",
      duration: "Two reporting weeks.", guardrails: "Cap spend.", decision_rule: "Compare acquisition cost." },
    primary_success_metric: "CPA", secondary_metrics: ["Purchase CVR"],
    risks_and_limitations: ["Attribution cannot establish incremental sales."], confidence_rationale: "The cause remains uncertain.",
  },
}

function mount(path = "/ai-analyst/21") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>)
}

function stubRequests(enabled: boolean, handlePost?: (init: RequestInit) => Promise<Response>, analyses: () => Analysis[] = () => []) {
  return vi.fn((url: string, init?: RequestInit) => {
    const pathname = new URL(url, "http://localhost").pathname
    if (pathname.endsWith("/ai/status")) return Promise.resolve(Response.json({
      enabled, reason: enabled ? null : "DISABLED", request_limit_per_hour: 8, model: "mock-model", provider_status: "UNCHECKED",
    }))
    if (pathname.endsWith("/ai/status/check")) return Promise.resolve(Response.json({
      enabled: true, reason: "PROVIDER_ERROR", model: "mock-model", provider_status: "ERROR", provider_message: "The model is unavailable.",
    }))
    if (pathname.endsWith("/analyses")) {
      if (init?.method === "POST") {
        return handlePost!(init)
      }
      return Promise.resolve(Response.json(page(analyses())))
    }
    if (pathname.endsWith("/insights/21")) return Promise.resolve(Response.json(sampleFinding))
    if (pathname.endsWith("/insights")) return Promise.resolve(Response.json(page([sampleFinding])))
    throw new Error(`Unexpected request ${url}`)
  })
}

it("allows evidence and previous analysis review while AI is disabled", async () => {
  const mock = stubRequests(false, undefined, () => [{ ...completed, is_current: false }])
  vi.stubGlobal("fetch", mock)
  mount()
  expect(await screen.findByText("AI analysis is disabled for this workspace.")).toBeInTheDocument()
  expect(await screen.findByRole("heading", { name: "CPA deterioration" })).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Analyze with AI" })).toBeDisabled()
  expect(await screen.findByRole("heading", { name: "AI-generated interpretation" })).toBeInTheDocument()
  expect(screen.getByText("This is a previous analysis version. Its original evidence references remain available.")).toBeInTheDocument()
  expect(mock.mock.calls.every(([, init]) => init?.method !== "POST")).toBe(true)
})

it("calls AI on demand, shows pending state, and renders evidence references and the experiment", async () => {
  let done = false
  let finish: () => void = () => {}
  const mock = stubRequests(true, (init) => new Promise((resolve) => {
    expect(init.body).toBeUndefined()
    finish = () => { done = true; resolve(Response.json(completed, { status: 201 })) }
  }), () => done ? [completed] : [])
  vi.stubGlobal("fetch", mock)
  const user = userEvent.setup()
  mount()
  const button = await screen.findByRole("button", { name: "Analyze with AI" })
  await waitFor(() => expect(button).toBeEnabled())
  expect(mock.mock.calls.every(([, init]) => init?.method !== "POST")).toBe(true)
  await user.click(button)
  expect(await screen.findByText(/Generating an interpretation/)).toHaveAttribute("role", "status")
  finish()
  expect(await screen.findByRole("heading", { name: "AI-generated interpretation" })).toBeInTheDocument()
  expect(screen.getByText("current.metrics.cpa")).toBeInTheDocument()
  expect(screen.getByRole("heading", { name: "Proposed experiment" })).toBeInTheDocument()
  expect(screen.getByText("Keep one comparison cell unchanged.")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Analyze with AI" })).toBeDisabled()
})

it("displays a recoverable error and permits another explicit request", async () => {
  vi.stubGlobal("fetch", stubRequests(true, () => Promise.resolve(Response.json({
    error: { message: "The AI provider timed out. Try again." },
  }, { status: 504 }))))
  const user = userEvent.setup()
  mount()
  const button = await screen.findByRole("button", { name: "Analyze with AI" })
  await waitFor(() => expect(button).toBeEnabled())
  await user.click(button)
  expect(await screen.findByRole("alert")).toHaveTextContent("The AI provider timed out. Try again.")
  await waitFor(() => expect(screen.getByRole("button", { name: "Analyze with AI" })).toBeEnabled())
})

it("opens AI Analyst from Insights and checks provider access only on request", async () => {
  const mock = stubRequests(true)
  vi.stubGlobal("fetch", mock)
  const user = userEvent.setup()
  mount("/insights/21")
  await user.click(await screen.findByRole("link", { name: "Review in AI Analyst" }))
  expect(await screen.findByRole("heading", { name: "AI Analyst" })).toBeInTheDocument()
  expect(mock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0)
  await user.click(await screen.findByRole("button", { name: "Check OpenAI connection" }))
  expect(await screen.findByText("The model is unavailable.")).toBeInTheDocument()
  expect(mock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1)
})

it("sends an explicit regeneration against the latest analysis and preserves the earlier version", async () => {
  const replacement = { ...completed, id: 56 }
  let rows = [completed]
  const mock = stubRequests(true, (init) => {
    const body = JSON.parse(String(init.body))
    expect(body.regenerate_from).toBe(completed.id)
    expect(body.request_id).toMatch(/^[a-f0-9-]{36}$/)
    rows = [replacement, { ...completed, is_current: false }]
    return Promise.resolve(Response.json(replacement, { status: 201 }))
  }, () => rows)
  vi.stubGlobal("fetch", mock)
  const user = userEvent.setup()
  mount()
  const button = await screen.findByRole("button", { name: "Regenerate analysis" })
  expect(mock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0)
  await user.click(button)
  expect(await screen.findByText(/Analysis #56 ·/)).toBeInTheDocument()
  await user.selectOptions(screen.getByLabelText("Analysis version"), "55")
  expect(screen.getByText(/Analysis #55 ·/)).toBeInTheDocument()
  expect(mock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1)
})

it("offers a finding selection when the analyst opens without a finding", async () => {
  const mock = stubRequests(true)
  vi.stubGlobal("fetch", mock)
  mount("/ai-analyst")
  expect(await screen.findByText("Choose a verified finding")).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Analyze with AI" })).not.toBeInTheDocument()
  expect(mock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0)
})
