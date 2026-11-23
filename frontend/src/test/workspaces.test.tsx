import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router"
import { describe, expect, it, vi } from "vitest"

import { App } from "@/app"
import type { Campaign, ImportPreview, ImportRecord, Metrics, Report } from "@/lib/api"

const metrics: Metrics = {
  spend: "125.25", impressions: "9007199254740993", clicks: 100, attributed_purchases: "5",
  attributed_purchase_value: "550", ctr: "10", cpc: "1.2525", cpm: "125.25",
  purchase_cvr: "5", cpa: "25.05", roas: "4.391217564870", attributed_aov: "110",
}
const report: Report = {
  metrics, first_date: "2026-08-25", last_date: "2026-08-25",
  latest_import_at: "2026-11-23T12:00:00Z", record_count: 1, observed_days: 1,
  fictional_record_count: 1, platform_attributed_overlap: false, conversion_status: "available",
  attribution_contexts: [{ conversion_action: "PURCHASE", attribution_method: "LAST_CLICK", attribution_window: "7D_CLICK", date_basis: "INTERACTION_DATE" }],
}
const first: Campaign = {
  id: 1, campaign_name: "Trail Collection Search", external_campaign_id: "NS-G01", platform: "GOOGLE_ADS",
  status: "ACTIVE", objective: "PURCHASES", currency: "USD", start_date: "2026-08-25",
  end_date: null, target_cpa: "28", target_roas: "4", missing_days: 0,
  cpa_target_status: "met", roas_target_status: "met", report,
}
const second: Campaign = { ...first, id: 2, platform: "META_ADS", campaign_name: "Lifestyle Prospecting" }
const noData: Report = {
  metrics: null, first_date: null, last_date: null, latest_import_at: null, record_count: 0,
  observed_days: 0, fictional_record_count: 0, platform_attributed_overlap: false,
  conversion_status: "empty", attribution_contexts: [],
}

function page<T>(items: T[]) { return { items, page: 1, page_size: 25, total: items.length } }

function mount(path = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>)
}

function mockApi(handler?: (url: URL, init?: RequestInit) => Response | Promise<Response> | undefined) {
  const fetchMock = vi.fn((input: string, init?: RequestInit) => {
    const url = new URL(input, "http://test.local")
    const custom = handler?.(url, init)
    if (custom) return Promise.resolve(custom)
    switch (url.pathname) {
      case "/api/v1/campaign-options": return Promise.resolve(Response.json(page([first, second])))
      case "/api/v1/analytics/overview": return Promise.resolve(Response.json(report))
      case "/api/v1/analytics/trends": return Promise.resolve(Response.json({
        items: [{ date: "2026-08-25", metrics }], first_date: "2026-08-25", last_date: "2026-08-25",
      }))
      case "/api/v1/analytics/platforms": return Promise.resolve(Response.json([]))
      case "/api/v1/campaigns": return Promise.resolve(Response.json(page([first, second])))
      case "/api/v1/imports": return Promise.resolve(Response.json(page([])))
      default: throw new Error(`Unexpected request to ${url}`)
    }
  })
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

describe("overview", () => {
  it("shows loading followed by the values returned by the API", async () => {
    let respond: (response: Response) => void = () => {}
    mockApi((url) => url.pathname.endsWith("/overview") ? new Promise((resolve) => { respond = resolve }) : undefined)
    mount()
    expect(screen.getByRole("status")).toHaveTextContent("Loading performance data")
    respond(Response.json(report))
    const cards = await screen.findByRole("region", { name: "Performance metrics" })
    expect(within(cards).getByText("$125.25")).toBeInTheDocument()
    expect(within(cards).getByText("4.39×")).toBeInTheDocument()
    expect(within(cards).getByText("10.00%")).toBeInTheDocument()
    expect(within(cards).getByText("9,007,199,254,740,993")).toBeInTheDocument()
    expect(screen.getByText("Fictional data")).toBeInTheDocument()
  })

  it("sends inclusive date, platform and campaign filters", async () => {
    const calls = mockApi()
    const user = userEvent.setup()
    mount()
    await screen.findByRole("region", { name: "Performance metrics" })
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-08-25" } })
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-08-26" } })
    await user.selectOptions(screen.getByLabelText("Platform"), "META_ADS")
    await user.selectOptions(screen.getByLabelText("Campaign"), "2")
    await waitFor(() => {
      const request = calls.mock.calls.map(([url]) => new URL(url, "http://test.local"))
        .find((url) => url.pathname.endsWith("/overview") && url.searchParams.get("campaign_id") === "2")
      expect(Object.fromEntries(request?.searchParams ?? [])).toEqual({
        start_date: "2026-08-25", end_date: "2026-08-26", platform: "META_ADS", campaign_id: "2",
      })
    })
  })

  it("renders an empty state for a period without rows", async () => {
    mockApi((url) => url.pathname.endsWith("/overview") ? Response.json(noData) : undefined)
    mount("/?start_date=2026-01-01&end_date=2026-01-02")
    expect(await screen.findByText("No performance data")).toBeInTheDocument()
    expect(screen.queryByRole("region", { name: "Performance metrics" })).not.toBeInTheDocument()
  })

  it("shows an API error and retries successfully", async () => {
    let attempts = 0
    mockApi((url) => url.pathname.endsWith("/overview") && attempts++ === 0
      ? Response.json({ error: { message: "Database unavailable" } }, { status: 503 }) : undefined)
    const user = userEvent.setup()
    mount()
    expect(await screen.findByRole("alert")).toHaveTextContent("Database unavailable")
    await user.click(screen.getByRole("button", { name: "Try again" }))
    expect(await screen.findByRole("region", { name: "Performance metrics" })).toBeInTheDocument()
  })
})

describe("campaigns", () => {
  it("requests backend sorting and displays the returned order", async () => {
    const calls = mockApi((url) => url.pathname.endsWith("/campaigns") && url.searchParams.get("direction") === "asc"
      ? Response.json(page([second, first])) : undefined)
    const user = userEvent.setup()
    mount("/campaigns")
    const original = await screen.findByRole("table", { name: "Campaign performance" })
    expect(within(original).getAllByRole("row")[1]).toHaveTextContent("Trail Collection Search")
    await user.click(screen.getByRole("button", { name: "Sort by Spend" }))
    const sorted = await screen.findByRole("table", { name: "Campaign performance" })
    expect(within(sorted).getAllByRole("row")[1]).toHaveTextContent("Lifestyle Prospecting")
    expect(screen.getByRole("button", { name: "Sort by Spend" }).closest("th")).toHaveAttribute("aria-sort", "ascending")
    expect(calls.mock.calls.some(([url]) => url.includes("sort=spend&direction=asc"))).toBe(true)
  })
})

describe("CSV imports", () => {
  it("previews server-parsed rows, displays validation, and confirms the reviewed token", async () => {
    const user = userEvent.setup()
    const preview: ImportPreview = {
      token: "preview-token", total_rows: 2, valid_rows: 1, duplicate_rows: 0, rejected_rows: 1,
      issue_count: 1, error_counts: { UNSUPPORTED_CURRENCY: 1 },
      rows: [{ row_number: 2, status: "valid", values: { date: "2026-08-25", campaign_name: "Preview campaign" } }],
      issues: [{ row_number: 3, field_name: "currency", error_code: "UNSUPPORTED_CURRENCY", error_message: "CampaignIQ currently accepts USD only." }],
    }
    const record: ImportRecord = {
      id: 1, filename: "test.csv", source_platform: "GOOGLE_ADS", imported_at: "2026-11-23T12:00:00Z",
      total_rows: 2, valid_rows: 1, duplicate_rows: 0, rejected_rows: 1,
      import_status: "COMPLETED_WITH_ERRORS", source_type: "CSV_UPLOAD", validation_summary: { error_counts: {} },
    }
    let confirmed = false
    mockApi((url, init) => {
      if (url.pathname.endsWith("/preview")) {
        const file = (init?.body as FormData).get("file") as File
        expect(file.name).toBe("test.csv")
        return Response.json(preview)
      }
      if (url.pathname.endsWith("/commit")) {
        expect((init?.body as FormData).get("preview_token")).toBe("preview-token")
        confirmed = true
        return Response.json(record, { status: 201 })
      }
      if (url.pathname.endsWith("/imports") && confirmed) return Response.json(page([record]))
      return undefined
    })
    mount("/imports")
    expect(await screen.findByText("No imports yet")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Preview CSV" })).toBeDisabled()
    await user.upload(screen.getByLabelText("Choose a CSV file"), new File(["example"], "test.csv", { type: "text/csv" }))
    await user.click(screen.getByRole("button", { name: "Preview CSV" }))
    expect(await screen.findByRole("table", { name: "CSV preview" })).toHaveTextContent("Preview campaign")
    expect(screen.getByRole("table", { name: "Validation issues" })).toHaveTextContent("CampaignIQ currently accepts USD only.")
    await user.click(screen.getByRole("button", { name: "Import 1 row" }))
    expect(await screen.findByText(/1 imported/)).toBeInTheDocument()
    expect(await screen.findByRole("button", { name: "test.csv" })).toBeInTheDocument()
  })
})
