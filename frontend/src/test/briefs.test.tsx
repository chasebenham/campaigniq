import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router"
import { expect, it, vi } from "vitest"

import { App } from "@/app"
import { type CommentaryRequest, type CommentaryResult, type Document, type Draft, type VersionView } from "@/lib/briefs"
import { page, sampleFinding } from "./detection-fixtures"

const period = { start: "2026-09-01", end: "2026-09-07" }
const stamp = "2026-09-20T15:00:00Z"
const source = { ...sampleFinding, current_evidence: { ...sampleFinding.current_evidence, ...period } }
const digest = "7".repeat(64)
const title = "Fictional leadership review"

function document(draft: Draft): Document {
  return {
    title: draft.title, period: draft.sources.period, generated_at: stamp, template_version: "1.0.0",
    provenance: "Portfolio reporting archive · Fictional", sections: [{
      title: "Executive Summary", blocks: [{
        title: null, source: "management", bullets: [], paragraphs: [draft.narrative.executive_summary],
        tables: [{ headers: ["Metric", "Portfolio"], rows: [["Spend", "$150.00"]], caption: null }],
      }],
    }],
  }
}

function mount(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>)
}

const generated = {
  executive_summary: "Consider the reporting limitations before acting.",
  recommendations: "Review campaign-level CPA and evidence coverage.",
  commentary: "Spend allocation decisions depend on comparable measurements.",
  experiment: "Reconcile the reported observations before planning an experiment.",
  next_decisions: "Confirm the eligible data before reviewing the next budget decision.",
}
function generatedResult(target: CommentaryRequest["target"]): CommentaryResult {
  const fields = target === "all" ? generated : { [target]: generated[target] }
  return { fields, provenance: Object.fromEntries(Object.keys(fields).map(key => [key, {
    id: 43, model: "gpt-6-luna", prompt_version: "commentary-1", schema_version: "1.0.0", evidence_fingerprint: digest,
    generated_at: stamp, usage: null, references: ["performance.overview"], authorship: "AI_GENERATED", stale: false,
  }])) }
}

function mockApi(aiEnabled = false, commentary?: (body: CommentaryRequest) => Response | Promise<Response>) {
  const records: VersionView[] = []
  const calls = vi.fn(async (input: string, init?: RequestInit) => {
    const url = new URL(input, "http://localhost")
    const path = url.pathname
    const method = init?.method ?? "GET"
    if (path.endsWith("/ai/status")) return Response.json({ enabled: aiEnabled })
    if (path.endsWith("/insights/21")) return Response.json(source)
    if (path.endsWith("/budget-lab/scenarios")) return Response.json(page([{ id: 18, name: "Fictional Holiday Mix", status: "CURRENT" }]))
    if (path.endsWith("/defaults")) return Response.json({ period, suggested_run_id: 4 })
    if (path.endsWith("/sources")) return Response.json({ suggested_run_id: 4, findings: page([
      { finding: source, analyses: [{ id: 11, model: "gpt-6-luna", created_at: stamp, historical: false }], suggested: true },
    ]) })
    if (path.endsWith("/draft-commentary")) {
      const body = JSON.parse(String(init?.body)) as CommentaryRequest
      return commentary?.(body) ?? Response.json(generatedResult(body.target))
    }
    if (path.endsWith("/preview")) {
      const draft = JSON.parse(String(init?.body)) as Draft
      return Response.json({ document: document(draft), evidence_fingerprint: digest, warnings: [] })
    }
    if (path.endsWith("/generate-summary") && method === "POST") {
      const current = records.at(-1)!
      const generation = { id: 31, version: current.version, status: "COMPLETED", model: "gpt-6-luna",
        text: "Investigate the available performance signals and review missing evidence before reallocating spend.",
        references: ["performance.overview"], error: null, usage: null } as const
      current.generation = { ...generation, references: [...generation.references] }
      return Response.json(generation)
    }
    if (method === "POST" || method === "PUT") {
      const body = JSON.parse(String(init?.body))
      const { evidence_fingerprint, ...draft } = body as Draft & { evidence_fingerprint: string }
      const version = records.length + 1
      const row: VersionView = {
        brief_id: 5, title: draft.title, period, version, current_version: version, generated_at: stamp, freshness: "CURRENT",
        template_version: "1.0.0", draft: { ...draft, base_version: version }, evidence_fingerprint, warnings: [],
        document: document(draft), generation: null,
      }
      records.push(row)
      return Response.json(row, { status: 201 })
    }
    if (path.endsWith("/strategy-briefs")) return Response.json(page(records.length ? [{
      id: 5, title, period, updated_at: stamp, created_at: stamp, current_version: records.length, status: "SAVED", freshness: "CURRENT",
    }] : []))
    if (path.endsWith("/versions")) return Response.json(page([...records].reverse()))
    if (path.endsWith("/5")) return Response.json(records.at(-1))
    if (path.endsWith("/versions/1")) return Response.json({ ...records[0], current_version: records.length })
    throw new Error(`Unexpected request ${input}`)
  })
  vi.stubGlobal("fetch", calls)
  return calls
}

it("builds and saves a brief with explicitly selected findings, AI interpretation, and a budget", async () => {
  const requests = mockApi()
  const user = userEvent.setup()
  const view = mount("/strategy-briefs")
  expect(await screen.findByText("No strategy briefs yet")).toBeInTheDocument()
  await user.click(screen.getByRole("link", { name: "Create Strategy Brief" }))
  const checkbox = await screen.findByRole("checkbox", { name: /Trail Collection Search/ })
  expect(checkbox).not.toBeChecked()
  await user.click(checkbox)
  await user.selectOptions(screen.getByLabelText("AI analysis for finding #21"), "11")
  await user.selectOptions(screen.getByLabelText("Budget scenario"), "18")
  fireEvent.change(screen.getByLabelText("Report title"), { target: { value: title } })
  fireEvent.change(screen.getByLabelText("Executive summary"), { target: { value: "Investigate acquisition costs." } })
  expect(screen.getByRole("button", { name: "Save strategy brief" })).toBeDisabled()
  expect(screen.getByRole("button", { name: "Save strategy brief" })).toHaveAccessibleDescription(/Select Preview report before saving/)
  await user.click(screen.getByRole("button", { name: "Preview report" }))
  expect(await screen.findByText("$150.00")).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "Save strategy brief" }))
  expect(await screen.findByRole("heading", { name: title, level: 1 })).toBeInTheDocument()
  const body = JSON.parse(String(requests.mock.calls.find(([url, options]) => url.endsWith("/strategy-briefs") && options?.method === "POST")?.[1]?.body))
  expect(body.sources).toEqual({ period, findings: [{ finding_id: 21, analysis_id: 11 }], budget_id: 18 })
  expect(await screen.findByText("AI is unavailable.", { exact: false })).toBeInTheDocument()
  expect(screen.getAllByRole("link", { name: "Export PDF for version 1" })[0]).toHaveAttribute("href", "/api/v1/strategy-briefs/5/export/pdf?version=1")
  view.unmount()

  mount("/strategy-briefs")
  await user.click(await screen.findByRole("link", { name: title }))
  await user.click(await screen.findByRole("link", { name: "Revise brief" }))
  await user.click(await screen.findByRole("button", { name: "Preview report" }))
  expect(await screen.findByRole("button", { name: "Save new version" })).toBeEnabled()
  fireEvent.change(await screen.findByLabelText("Executive summary"), { target: { value: "Check whether cost changes are attributable." } })
  expect(screen.getByRole("button", { name: "Save new version" })).toBeDisabled()
  expect(screen.getByRole("button", { name: "Save new version" })).toHaveAccessibleDescription(/Preview your changes before saving/)
  await user.click(screen.getByRole("button", { name: "Preview report" }))
  await user.click(await screen.findByRole("button", { name: "Save new version" }))
  const history = await screen.findByRole("table", { name: "Strategy brief version history" })
  await user.click(await within(history).findByRole("link", { name: "Version 1" }))
  expect(await screen.findByText("Investigate acquisition costs.")).toBeInTheDocument()
  expect(screen.queryByText("Check whether cost changes are attributable.")).not.toBeInTheDocument()
  expect(requests.mock.calls.every(([url]) => !url.endsWith("/generate-summary"))).toBe(true)
})

it("uses linked evidence only after an explicit choice", async () => {
  const requests = mockApi()
  const user = userEvent.setup()
  mount("/strategy-briefs/new?finding_id=21&analysis_id=11")
  expect(await screen.findByText("0 selected")).toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "Include linked analysis #11" }))
  expect(await screen.findByText("1 selected")).toBeInTheDocument()
  expect(screen.getByLabelText("AI analysis for finding #21")).toHaveValue("11")
  expect(requests.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

it("identifies missing report fields and allows a basic preview once they are supplied", async () => {
  const requests = mockApi()
  mount("/strategy-briefs/new")
  const preview = await screen.findByRole("button", { name: "Preview report" })
  const reportTitle = screen.getByLabelText("Report title")
  const reportEnd = screen.getByLabelText("Reporting end")
  fireEvent.change(reportTitle, { target: { value: " " } })
  fireEvent.change(reportEnd, { target: { value: "" } })
  expect(preview).toBeDisabled()
  expect(preview).toHaveAccessibleDescription(/Enter a report title\. Enter the reporting end date\./)
  fireEvent.change(reportTitle, { target: { value: "New report" } })
  fireEvent.change(reportEnd, { target: { value: "2026-08-30" } })
  expect(preview).toHaveAccessibleDescription(/Choose a reporting end date on or after the start date/)
  fireEvent.change(reportEnd, { target: { value: period.end } })
  expect(preview).toBeEnabled()
  expect(requests.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})

it("shows a recoverable listing error", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(Response.json({ error: { message: "Reports are temporarily unavailable." } }, { status: 503 }))))
  mount("/strategy-briefs")
  expect(await screen.findByRole("alert")).toHaveTextContent("Reports are temporarily unavailable.")
  expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument()
})

it("requests optional synthesis only when clicked and applies it through a revision", async () => {
  const requests = mockApi(true)
  const user = userEvent.setup()
  mount("/strategy-briefs/new")
  await user.click(await screen.findByRole("button", { name: "Preview report" }))
  await user.click(await screen.findByRole("button", { name: "Save strategy brief" }))
  const summarize = await screen.findByRole("button", { name: "Generate Executive Summary with AI" })
  expect(requests.mock.calls.filter(([url]) => url.endsWith("/generate-summary"))).toHaveLength(0)
  await user.click(summarize)
  await user.click(await screen.findByRole("link", { name: "Use proposal in a revision" }))
  expect(await screen.findByLabelText("Executive summary")).toHaveValue(
    "Investigate the available performance signals and review missing evidence before reallocating spend.",
  )
  expect(requests.mock.calls.filter(([url]) => url.endsWith("/generate-summary"))).toHaveLength(1)
  expect(requests.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(false)
})

it("drafts an individual field, protects manual edits, and saves the reviewed text", async () => {
  const requests = mockApi(true)
  const user = userEvent.setup()
  mount("/strategy-briefs/new")
  const generate = await screen.findByRole("button", { name: "Generate Executive summary with AI" })
  const summary = screen.getByLabelText("Executive summary")
  fireEvent.change(screen.getByLabelText("Management commentary"), { target: { value: "Keep this manual context." } })
  await user.click(generate)
  expect(await screen.findByText("Draft added. Review or edit it before saving.")).toBeInTheDocument()
  expect(summary).toHaveValue(generated.executive_summary)
  expect(screen.getByLabelText("Management commentary")).toHaveValue("Keep this manual context.")
  fireEvent.change(summary, { target: { value: "Edited by a manager." } })
  expect(screen.getByText(/AI draft · edited by management/)).toBeInTheDocument()
  await user.click(generate)
  await user.click(screen.getByRole("button", { name: "Keep current text" }))
  expect(summary).toHaveValue("Edited by a manager.")
  expect(requests.mock.calls.filter(([url]) => url.endsWith("/draft-commentary"))).toHaveLength(1)
  await user.click(screen.getByRole("button", { name: "Preview report" }))
  await user.click(await screen.findByRole("button", { name: "Save strategy brief" }))
  expect(await screen.findByText("Edited by a manager.")).toBeInTheDocument()
  expect(screen.getAllByRole("link", { name: "Export PDF for version 1" })[0]).toHaveAttribute("href", "/api/v1/strategy-briefs/5/export/pdf?version=1")
  await user.click(screen.getByRole("link", { name: "Revise brief" }))
  expect(await screen.findByLabelText("Executive summary")).toHaveValue("Edited by a manager.")
})

it("confirms before replacing a populated field with Draft All Five and sends one request", async () => {
  const requests = mockApi(true)
  const user = userEvent.setup()
  mount("/strategy-briefs/new")
  fireEvent.change(await screen.findByLabelText("Next decisions"), { target: { value: "Original decision." } })
  await user.click(screen.getByRole("button", { name: "Draft All Five" }))
  expect(screen.getByRole("group", { name: "Confirm commentary replacement" })).toHaveTextContent("Next decisions")
  expect(requests.mock.calls.filter(([url]) => url.endsWith("/draft-commentary"))).toHaveLength(0)
  await user.click(screen.getByRole("button", { name: "Replace and draft" }))
  expect(await screen.findByText("All five drafts are ready to review.")).toBeInTheDocument()
  expect(screen.getByLabelText("Management experiment proposal")).toHaveValue(generated.experiment)
  expect(screen.getByLabelText("Next decisions")).toHaveValue(generated.next_decisions)
  expect(requests.mock.calls.filter(([url]) => url.endsWith("/draft-commentary"))).toHaveLength(1)
  fireEvent.change(screen.getByLabelText("Reporting end"), { target: { value: "2026-09-08" } })
  expect(screen.getByRole("button", { name: "Regenerate Next decisions with AI" })).toBeEnabled()
  expect(screen.getByLabelText("Next decisions")).toHaveValue(generated.next_decisions)
})

it("holds late drafts after selection changes and preserves existing content on validation errors", async () => {
  let finish!: (response: Response) => void
  let calls = 0
  mockApi(true, () => ++calls === 1 ? new Promise(resolve => { finish = resolve }) :
    Response.json({ error: { message: "Draft failed validation." } }, { status: 502 }))
  const user = userEvent.setup()
  mount("/strategy-briefs/new")
  const gen = await screen.findByRole("button", { name: "Generate Strategic recommendations with AI" })
  await user.click(gen)
  expect(gen).toHaveTextContent("Drafting")
  expect(screen.getByRole("button", { name: "Generate Executive summary with AI" })).toHaveTextContent("Generate with AI")
  fireEvent.change(screen.getByLabelText("Reporting end"), { target: { value: "2026-09-08" } })
  finish(Response.json(generatedResult("recommendations")))
  expect(await screen.findByText(/Evidence selections changed during drafting/)).toBeInTheDocument()
  const input = screen.getByLabelText("Strategic recommendations")
  expect(input).toHaveValue("")
  expect(screen.queryByRole("button", { name: "Apply returned draft" })).not.toBeInTheDocument()
  fireEvent.change(input, { target: { value: "Manual draft stays." } })
  await user.click(gen)
  await user.click(screen.getByRole("button", { name: "Replace and draft" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("Draft failed validation. No commentary was replaced.")
  expect(input).toHaveValue("Manual draft stays.")
})
