export type Provider = {
  provider: string
  default: boolean
  model: string
  endpoint: string
  thinking_level: string
  credential: string
  ready: boolean
  external: boolean
  may_charge: boolean
  automatic: boolean
  data_destination: string
}

export type CaseRecord = {
  case_id: string
  name: string
  slug: string
  status: string
  created_at: string
  updated_at: string
  description: string
  tags: string[]
  node_count?: number
  edge_count?: number
  scan_count?: number
  review_count?: number
  nodes?: number
  edges?: number
  pending_reviews?: number
}

export type EvidenceNode = {
  node_id: string
  entity_type: string
  label: string
  value: string
  canonical_value: string
  confidence: number
  confidence_label: string
  sources: string[]
  evidence_refs: string[]
  attributes: Record<string, unknown>
  first_seen: string
  last_seen: string
  manual: boolean
}

export type ConfidenceFactor = {
  label: string
  effect: string
  weight: number
  explanation: string
}

export type EvidenceEdge = {
  edge_id: string
  source_node_id: string
  target_node_id: string
  relation: string
  label: string
  confidence: number
  confidence_label: string
  reasons: string[]
  factors: ConfidenceFactor[]
  evidence_refs: string[]
  attributes: Record<string, unknown>
}

export type TimelineEvent = {
  event_id: string
  title: string
  event_type: string
  occurred_at: string
  node_id?: string
  source?: string
  attributes: Record<string, unknown>
}

export type ReviewTask = {
  task_id: string
  title: string
  description: string
  priority: string
  status: string
  evidence_ids: string[]
  recommended_action: string
  resolution_note: string
}

export type IdentityCluster = {
  cluster_id: string
  label: string
  node_ids: string[]
  confidence: number
  confidence_label: string
  reasons: string[]
  contradictions: string[]
}

export type CasePayload = {
  case: CaseRecord
  nodes: EvidenceNode[]
  edges: EvidenceEdge[]
  timeline: TimelineEvent[]
  scans: Array<Record<string, unknown>>
  notes: string
  attachments: Array<Record<string, unknown>>
  verifications: Array<Record<string, unknown>>
  clusters: IdentityCluster[]
  review_tasks: ReviewTask[]
  deep_seeds: Array<Record<string, unknown>>
  analysis: Record<string, unknown> | null
  screenshots: string[]
}

export type OverviewPayload = {
  stats: {
    cases: number
    open_cases: number
    nodes: number
    edges: number
    pending_reviews: number
    installed_tools: number
    catalog_tools: number
  }
  recent_cases: CaseRecord[]
  providers: Provider[]
  operations: OperationState[]
}

export type PackageTool = {
  id: string
  name: string
  categories: string[]
  integration: string
  risk: string
  installed: boolean
  executable?: string
  source?: string
  managed: boolean
  setup_required: boolean
  api_keys: string[]
  unmaintained: boolean
  platform_supported: boolean
  platform_detail: string
}

export type OperationEvent = {
  type: string
  at: string
  message: string
  current: string
  progress: number
  data: Record<string, unknown>
}

export type OperationState = {
  operation_id: string
  kind: string
  title: string
  status: string
  progress: number
  current: string
  message: string
  created_at: string
  updated_at: string
  started_at?: string
  finished_at?: string
  result?: Record<string, unknown>
  error?: string
  events: OperationEvent[]
}
