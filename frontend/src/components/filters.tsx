import { ChevronDown } from "lucide-react"
import { useId, type ReactNode } from "react"
import { useSearchParams } from "react-router"

import type { CampaignOption, Filters } from "@/lib/api"
import { platformNames } from "@/lib/presentation"
import { Button } from "./ui/button"
import { Card } from "./ui/card"

export function useReportFilters(keys: (keyof Filters)[] = ["start_date", "end_date", "platform", "campaign_id"]) {
  const [params, setParams] = useSearchParams()
  const filters: Filters = {}
  for (const key of keys) {
    const value = params.get(key)
    if (value) filters[key] = value
  }
  const invalid = Boolean(filters.start_date && filters.end_date && filters.start_date > filters.end_date)

  function change(updates: Record<string, string>) {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(updates)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    setParams(next, { replace: true })
  }

  function setFilter(key: keyof Filters, value: string) {
    change({ [key]: value, page: "", ...(key === "platform" ? { campaign_id: "" } : {}) })
  }

  return { filters, invalid, params, change, setFilter }
}

export function SelectField({ label, value, onChange, children, disabled = false }: {
  label: string; value: string; onChange: (value: string) => void; children: ReactNode; disabled?: boolean;
}) {
  const id = useId()
  return <div className="filter-field">
    <label htmlFor={id}>{label}</label>
    <span className="select-wrap">
      <select id={id} value={value} onChange={(event) => onChange(event.currentTarget.value)} disabled={disabled}>{children}</select>
      <ChevronDown size={15} aria-hidden="true" />
    </span>
  </div>
}

export function FilterBar({ filters, setFilter, reset, invalid, campaigns, optionsUnavailable = false, dateOnly = false, children }: {
  filters: Filters; setFilter: (key: keyof Filters, value: string) => void; reset: () => void;
  invalid: boolean; campaigns?: CampaignOption[]; optionsUnavailable?: boolean; dateOnly?: boolean; children?: ReactNode;
}) {
  const matching = campaigns?.filter((item) => !filters.platform || item.platform === filters.platform)
  return <Card className="filter-card" aria-label="Report filters">
    <div className="filter-bar">
      <label className="filter-field"><span>From</span><input type="date" value={filters.start_date ?? ""} onChange={(e) => setFilter("start_date", e.target.value)} /></label>
      <label className="filter-field"><span>To</span><input type="date" value={filters.end_date ?? ""} onChange={(e) => setFilter("end_date", e.target.value)} /></label>
      {!dateOnly && <SelectField label="Platform" value={filters.platform ?? ""} onChange={(value) => setFilter("platform", value)}>
        <option value="">All platforms</option>
        {Object.entries(platformNames).map(([key, name]) => <option key={key} value={key}>{name}</option>)}
      </SelectField>}
      {campaigns !== undefined && <SelectField label="Campaign" value={filters.campaign_id ?? ""} disabled={optionsUnavailable} onChange={(value) => setFilter("campaign_id", value)}>
        <option value="">{optionsUnavailable ? "Campaigns unavailable" : "All campaigns"}</option>
        {matching?.map((campaign) => <option key={campaign.id} value={campaign.id}>{campaign.campaign_name} · {platformNames[campaign.platform]}</option>)}
      </SelectField>}
      {children}
      <Button variant="ghost" onClick={reset} className="filter-reset">Clear filters</Button>
    </div>
    {invalid && <p className="filter-error" role="alert">The start date must be on or before the end date.</p>}
  </Card>
}
