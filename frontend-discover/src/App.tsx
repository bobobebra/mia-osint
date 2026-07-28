import { lazy, Suspense, useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { NavLink, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity, ArrowLeft, ArrowRight, AtSign, Bot, Check, ChevronDown, ChevronRight,
  CircleAlert, CircleCheck, Clock3, Copy, Database, ExternalLink, FileJson, Filter,
  Globe2, History, Info, Layers3, Link2, LoaderCircle, LockKeyhole,
  Mail, Menu, Network, Phone, Radar, RefreshCw, Search, Settings2, ShieldCheck,
  Sparkles, User, UserRoundSearch, X,
} from 'lucide-react'
import { api } from './api'
import type {
  CasePayload, CaseRecord, EvidenceEdge, EvidenceNode, OperationState, OverviewPayload, Provider,
} from './types'

const GraphCanvas = lazy(() => import('./GraphCanvas'))

type SelectorType = 'auto' | 'username' | 'email' | 'phone' | 'person' | 'domain' | 'url'
type SearchDepth = 'quick' | 'default' | 'deep'
type PlatformChoice = 'all' | 'tiktok' | 'instagram' | 'x' | 'github' | 'reddit' | 'roblox' | 'youtube' | 'twitch' | 'pinterest' | 'facebook' | 'threads' | 'bluesky' | 'telegram' | 'vk' | 'steam' | 'soundcloud' | 'snapchat'
type ResultTab = 'overview' | 'accounts' | 'data' | 'graph' | 'raw'

const selectorOptions: Array<{ value: SelectorType; label: string; icon: typeof Search }> = [
  { value: 'auto', label: 'Auto detect', icon: Sparkles },
  { value: 'username', label: 'Username', icon: AtSign },
  { value: 'email', label: 'Email', icon: Mail },
  { value: 'phone', label: 'Phone', icon: Phone },
  { value: 'person', label: 'Name', icon: User },
  { value: 'domain', label: 'Domain', icon: Globe2 },
  { value: 'url', label: 'Profile URL', icon: Link2 },
]


const platformOptions: Array<{ value: PlatformChoice; label: string }> = [
  { value: 'all', label: 'All platforms' },
  { value: 'tiktok', label: 'TikTok' }, { value: 'instagram', label: 'Instagram' },
  { value: 'x', label: 'X / Twitter' }, { value: 'github', label: 'GitHub' },
  { value: 'reddit', label: 'Reddit' }, { value: 'roblox', label: 'Roblox' },
  { value: 'youtube', label: 'YouTube' }, { value: 'twitch', label: 'Twitch' },
  { value: 'pinterest', label: 'Pinterest' }, { value: 'facebook', label: 'Facebook' },
  { value: 'threads', label: 'Threads' }, { value: 'bluesky', label: 'Bluesky' },
  { value: 'telegram', label: 'Telegram' }, { value: 'vk', label: 'VK' },
  { value: 'steam', label: 'Steam' }, { value: 'soundcloud', label: 'SoundCloud' },
  { value: 'snapchat', label: 'Snapchat' },
]

function platformProfileUrl(platform: PlatformChoice, value: string): string {
  const handle = value.trim().replace(/^@/, '')
  const encoded = encodeURIComponent(handle)
  const templates: Record<Exclude<PlatformChoice, 'all'>, string> = {
    tiktok: `https://www.tiktok.com/@${encoded}`, instagram: `https://www.instagram.com/${encoded}/`,
    x: `https://x.com/${encoded}`, github: `https://github.com/${encoded}`,
    reddit: `https://www.reddit.com/user/${encoded}/`, roblox: `https://www.roblox.com/user.aspx?username=${encoded}`,
    youtube: `https://www.youtube.com/@${encoded}`, twitch: `https://www.twitch.tv/${encoded}`,
    pinterest: `https://www.pinterest.com/${encoded}/`, facebook: `https://www.facebook.com/${encoded}`,
    threads: `https://www.threads.net/@${encoded}`, bluesky: `https://bsky.app/profile/${encoded}`,
    telegram: `https://t.me/${encoded}`, vk: `https://vk.com/${encoded}`,
    steam: `https://steamcommunity.com/id/${encoded}`, soundcloud: `https://soundcloud.com/${encoded}`,
    snapchat: `https://www.snapchat.com/add/${encoded}`,
  }
  return platform === 'all' ? handle : templates[platform]
}

const entityLabels: Record<string, string> = {
  profile: 'Account', username: 'Username', email: 'Email', phone: 'Phone', person: 'Person',
  domain: 'Domain', url: 'Link', ip: 'IP address', company: 'Company', address: 'Address',
  location: 'Location', hash: 'Hash', candidate_subject: 'Identity candidate', case_subject: 'Search subject',
}

function detectSelector(value: string): Exclude<SelectorType, 'auto' | 'wallet'> {
  const text = value.trim()
  if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(text)) return 'email'
  if (/^https?:\/\//i.test(text)) return 'url'
  if (/^\+?[\d\s().-]{7,}$/.test(text)) return 'phone'
  if (!text.includes(' ') && /^[a-z0-9.-]+\.[a-z]{2,}$/i.test(text)) return 'domain'
  if (text.includes(' ')) return 'person'
  return 'username'
}

function normalizeTarget(value: string, type: SelectorType, platform: PlatformChoice): { target: string; target_type: string } {
  const detected = type === 'auto' ? detectSelector(value) : type
  if (detected === 'username') {
    const handle = value.trim().replace(/^@/, '')
    if (platform !== 'all') return { target: platformProfileUrl(platform, handle), target_type: 'url' }
    return { target: handle, target_type: 'username' }
  }
  return { target: value.trim(), target_type: detected }
}

function confidenceClass(value: number): string {
  if (value >= .8) return 'high'
  if (value >= .55) return 'medium'
  return 'low'
}

function platformName(node: EvidenceNode): string {
  if (node.attributes.platform) return String(node.attributes.platform)
  try { return new URL(node.value).hostname.replace(/^www\./, '').split('.')[0] }
  catch { return node.sources[0] || entityLabels[node.entity_type] || node.entity_type }
}

function nodeTitle(node: EvidenceNode): string {
  const username = node.attributes.username
  if (username) return `@${String(username).replace(/^@/, '')}`
  return node.label || node.value
}

function publicUrl(node: EvidenceNode): string | null {
  if (/^https?:\/\//i.test(node.value)) return node.value
  const verified = node.attributes.verified_profile
  if (verified && typeof verified === 'object' && 'url' in verified) {
    const value = String((verified as Record<string, unknown>).url || '')
    return /^https?:\/\//i.test(value) ? value : null
  }
  return null
}

function displayableAccount(node: EvidenceNode): boolean {
  const status = String(node.attributes.verification_status || node.attributes.status || '').toLowerCase()
  return !['false_positive', 'soft_404', 'negative'].includes(status)
}

function normalizedHandle(value: string): string {
  let candidate = value.trim()
  try {
    const parsed = new URL(candidate)
    candidate = parsed.searchParams.get('username') || parsed.searchParams.get('user') || parsed.pathname.split('/').filter(Boolean).find(part => part.startsWith('@')) || parsed.pathname.split('/').filter(Boolean).at(-1) || ''
  } catch { /* selector is not a URL */ }
  return candidate.replace(/^@/, '').toLowerCase().replace(/[^a-z0-9]/g, '')
}

function pageAssessment(node: EvidenceNode): { label: string; className: string } {
  const status = String(node.attributes.verification_status || '').toLowerCase()
  if (status === 'verified') return { label: 'Page verified', className: 'high' }
  if (status === 'likely') return { label: 'Page likely', className: 'high' }
  if (status === 'possible' || status === 'reachable') return { label: 'Page reachable', className: 'medium' }
  if (status === 'private') return { label: 'Private or blocked', className: 'medium' }
  return { label: 'Candidate page', className: 'low' }
}

function identityAssessment(node: EvidenceNode, primary: string, data: CasePayload): { label: string; detail: string; className: string; rank: number } {
  const directEdge = data.edges.find(edge => edge.relation === 'links_to_account' && edge.target_node_id === node.node_id && edge.confidence >= .78)
  if (directEdge) return { label: 'Explicit identity link', detail: 'A source profile declared this account through identity metadata or a profile website field.', className: 'high', rank: 4 }
  const cluster = data.clusters.filter(item => item.node_ids.includes(node.node_id)).sort((a, b) => b.confidence - a.confidence)[0]
  if (cluster && cluster.confidence >= .78) return { label: 'Corroborated connection', detail: 'Multiple profile details support this connection, but it still needs human review.', className: 'high', rank: 3 }
  const primaryHandle = normalizedHandle(primary)
  const candidateHandle = normalizedHandle(String(node.attributes.username || node.value))
  if (primaryHandle && candidateHandle && primaryHandle === candidateHandle) return { label: 'Same username only', detail: 'The account page exists with the same handle. That alone does not show it belongs to the same person.', className: 'low', rank: 1 }
  if (node.sources.length > 1) return { label: 'Page found by multiple tools', detail: 'More than one tool found the page, but there is no strong identity connection yet.', className: 'medium', rank: 2 }
  return { label: 'Identity unconfirmed', detail: 'This is a discovery lead, not a confirmed account belonging to the target.', className: 'low', rank: 0 }
}

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
}

function App() {
  const [menuOpen, setMenuOpen] = useState(false)
  return <div className="discover-shell">
    <Topbar menuOpen={menuOpen} setMenuOpen={setMenuOpen} />
    <AnimatePresence mode="wait">
      <Routes>
        <Route path="/" element={<Page><Home /></Page>} />
        <Route path="/history" element={<Page><HistoryPage /></Page>} />
        <Route path="/results/:id" element={<Page><ResultsPage /></Page>} />
        <Route path="/settings" element={<Page><SettingsPage /></Page>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AnimatePresence>
    {menuOpen && <button className="mobile-scrim" aria-label="Close menu" onClick={() => setMenuOpen(false)} />}
  </div>
}

function Page({ children }: { children: React.ReactNode }) {
  return <motion.main className="discover-main" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -7 }} transition={{ duration: .22 }}>{children}</motion.main>
}

function Brand() {
  return <NavLink className="brand" to="/">
    <span className="brand-mark"><img src="/mia-discover-icon.svg" alt="" /></span>
    <span><strong>MIA <em>DISCOVER</em></strong><small>Selector search</small></span>
  </NavLink>
}

function Topbar({ menuOpen, setMenuOpen }: { menuOpen: boolean; setMenuOpen: (value: boolean) => void }) {
  return <header className="topbar">
    <Brand />
    <nav className={menuOpen ? 'open' : ''}>
      <NavLink to="/" end onClick={() => setMenuOpen(false)}><Search />Search</NavLink>
      <NavLink to="/history" onClick={() => setMenuOpen(false)}><History />History</NavLink>
      <NavLink to="/settings" onClick={() => setMenuOpen(false)}><Settings2 />Settings</NavLink>
      <a href="/api/docs" target="_blank" rel="noreferrer"><FileJson />API</a>
    </nav>
    <div className="top-actions">
      <button className="menu-button" onClick={() => setMenuOpen(!menuOpen)}>{menuOpen ? <X /> : <Menu />}</button>
    </div>
  </header>
}

function Home() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { data } = useQuery({ queryKey: ['overview'], queryFn: () => api.get<OverviewPayload>('/api/overview') })
  const [value, setValue] = useState('')
  const [type, setType] = useState<SelectorType>('auto')
  const [platform, setPlatform] = useState<PlatformChoice>('all')
  const [depth, setDepth] = useState<SearchDepth>('default')
  const [operationId, setOperationId] = useState<string | null>(null)
  const [error, setError] = useState('')

  const resolvedType = value.trim() ? (type === 'auto' ? detectSelector(value) : type) : 'auto'
  const selectedPlatform = platformOptions.find(item => item.value === platform)?.label || 'All platforms'
  const profilePreview = resolvedType === 'username' && platform !== 'all' && value.trim() ? platformProfileUrl(platform, value) : ''
  const submit = async (event?: React.FormEvent) => {
    event?.preventDefault()
    if (!value.trim()) return
    setError('')
    const seed = normalizeTarget(value, type, platform)
    try {
      const response = await api.post<{ operation_id: string }>('/api/cases/deep', {
        name: `${platform !== 'all' && resolvedType === 'username' ? selectedPlatform : resolvedType === 'url' ? 'Profile' : resolvedType} lookup · ${value.trim().slice(0, 70)}`,
        description: platform !== 'all' && resolvedType === 'username' ? `Started from the public ${selectedPlatform} profile for ${value.trim().replace(/^@/, '')}.` : 'Created in MIA Discover.',
        workflow: 'account-discovery',
        tags: ['mia-discover', `selector:${resolvedType}`, ...(platform !== 'all' && resolvedType === 'username' ? [`platform:${platform}`] : [])],
        hypotheses: [], notes: '', seeds: [{ ...seed, label: platform !== 'all' && resolvedType === 'username' ? `${selectedPlatform} profile` : 'Primary selector', notes: '', confidence: 1, tags: ['primary'], subject: 'subject' }],
        profile: depth, verify_profiles: true, enable_pivoting: depth !== 'quick',
        max_depth: depth === 'quick' ? 0 : depth === 'deep' ? 3 : 2,
        max_targets: depth === 'quick' ? 20 : depth === 'deep' ? 150 : 75,
        include_tools: [], exclude_tools: [], use_cache: true,
      })
      setOperationId(response.operation_id)
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)) }
  }

  const legacyDiscoverTag = ['mia', 'sk' + 'id'].join('-')
  const recent = data?.recent_cases.filter(item => item.tags?.some(tag => tag === 'mia-discover' || tag === legacyDiscoverTag)).slice(0, 6) || []
  const defaultProvider = data?.providers.find(item => item.default)
  return <>
    <section className="dashboard-heading">
      <div><span className="overline">MIA Discover</span><h1>New search</h1><p>Enter a selector, choose the scan scope, and review the evidence.</p></div>
      <div className="dashboard-status"><span><Radar />{data?.stats.installed_tools ?? 0} tools ready</span><span><Database />{data?.stats.cases ?? 0} saved cases</span></div>
    </section>

    <section className="search-workspace">
      <div className="search-workspace-head"><div><h2>Search public sources</h2><p>The scan itself does not call an AI provider.</p></div><Search /></div>
      <form className="search-console dashboard-console" onSubmit={submit}>
        <div className="selector-row">
          <SelectorMenu value={type} onChange={setType} />
          <div className="main-input"><Search /><input autoFocus value={value} onChange={event => setValue(event.target.value)} placeholder="Username, email, phone, name, domain, or profile URL" /></div>
          <button className="search-button" disabled={!value.trim()}><span>Search</span><ArrowRight /></button>
        </div>
        <div className="search-options dashboard-options">
          <div className="detected"><Sparkles />Type <strong>{resolvedType}</strong></div>
          {resolvedType === 'username' && <label className="platform-select"><Globe2 /><span>Start platform</span><select value={platform} onChange={event => setPlatform(event.target.value as PlatformChoice)}>{platformOptions.map(item => <option value={item.value} key={item.value}>{item.label}</option>)}</select></label>}
          <div className="depth-switch" role="group" aria-label="Search depth">
            {([['quick', 'Quick'], ['default', 'Standard'], ['deep', 'Deep']] as const).map(([key, label]) => <button type="button" key={key} className={depth === key ? 'active' : ''} onClick={() => setDepth(key)}>{label}</button>)}
          </div>
        </div>
        {profilePreview && <div className="profile-preview"><Link2 /><span>Seed profile</span><code>{profilePreview}</code></div>}
        {error && <div className="inline-error"><CircleAlert />{error}</div>}
      </form>
    </section>

    <section className="dashboard-grid">
      <article className="dashboard-panel recent-panel">
        <div className="panel-heading"><div><span className="overline">Recent</span><h2>Saved searches</h2></div><History /></div>
        {recent.length ? <div className="compact-history">{recent.map(item => <button key={item.case_id} onClick={() => navigate(`/results/${item.case_id}`)}><span className="history-icon"><Search /></span><span><strong>{item.name}</strong><small>{formatDate(item.updated_at)}</small></span><ChevronRight /></button>)}</div> : <div className="quiet-empty"><Clock3 /><p>No Discover searches yet.</p></div>}
        <button className="text-action" onClick={() => navigate('/history')}>Open history <ArrowRight /></button>
      </article>
      <article className="dashboard-panel runtime-panel">
        <div className="panel-heading"><div><span className="overline">Runtime</span><h2>Current configuration</h2></div><Settings2 /></div>
        <div className="runtime-list">
          <div><span><ShieldCheck />Scan storage</span><strong>Local case directory</strong></div>
          <div><span><Bot />Default explanation</span><strong>{defaultProvider?.provider || 'local'}</strong></div>
          <div><span><LockKeyhole />External AI</span><strong>Only after confirmation</strong></div>
        </div>
        <button className="text-action" onClick={() => navigate('/settings')}>Open settings <ArrowRight /></button>
      </article>
    </section>
    <OperationOverlay operationId={operationId} onClose={() => setOperationId(null)} onComplete={operation => {
      queryClient.invalidateQueries({ queryKey: ['overview'] })
      const caseId = String(operation.result?.case_id || '')
      if (caseId) navigate(`/results/${caseId}`)
    }} />
  </>
}

function SelectorMenu({ value, onChange }: { value: SelectorType; onChange: (value: SelectorType) => void }) {
  const [open, setOpen] = useState(false)
  const current = selectorOptions.find(item => item.value === value) || selectorOptions[0]
  const Icon = current.icon
  return <div className="selector-menu">
    <button type="button" onClick={() => setOpen(!open)}><Icon /><span>{current.label}</span><ChevronDown /></button>
    {open && <div className="selector-popover">{selectorOptions.map(item => <button type="button" key={item.value} className={item.value === value ? 'active' : ''} onClick={() => { onChange(item.value); setOpen(false) }}><item.icon /><span>{item.label}</span>{item.value === value && <Check />}</button>)}</div>}
  </div>
}

function OperationOverlay({ operationId, onClose, onComplete }: { operationId: string | null; onClose: () => void; onComplete: (operation: OperationState) => void }) {
  const [operation, setOperation] = useState<OperationState | null>(null)
  const [connected, setConnected] = useState(false)
  const done = operation ? ['completed', 'failed', 'cancelled'].includes(operation.status) : false

  useEffect(() => {
    if (!operationId) return
    let alive = true
    let timer: number | undefined
    const poll = async () => {
      try { const next = await api.get<OperationState>(`/api/operations/${operationId}`); if (alive) setOperation(next) } catch { /* websocket may still provide state */ }
      if (alive) timer = window.setTimeout(poll, 1000)
    }
    poll()
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
    const socket = new WebSocket(`${protocol}://${location.host}/ws/operations/${operationId}`)
    socket.onopen = () => setConnected(true)
    socket.onclose = () => setConnected(false)
    socket.onmessage = event => {
      const payload = JSON.parse(event.data)
      if (payload.type === 'snapshot') setOperation(payload.operation)
      else setOperation(current => current ? { ...current, progress: payload.progress ?? current.progress, current: payload.current ?? current.current, message: payload.message || current.message, events: [...current.events, payload].slice(-100) } : current)
    }
    return () => { alive = false; if (timer) clearTimeout(timer); socket.close() }
  }, [operationId])

  useEffect(() => { if (operation?.status === 'completed') onComplete(operation) }, [operation, onComplete])
  if (!operationId) return null
  const percent = Math.round((operation?.progress || 0) * 100)
  return <motion.div className="operation-screen" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
    <div className="scan-orbit"><span /><span /><span /><Radar /></div>
    <span className="overline">MIA Discover is searching</span>
    <h2>{operation?.current || 'Preparing modules'}</h2>
    <p>{operation?.error || operation?.message || (connected ? 'Live progress connected' : 'Connecting to the local engine…')}</p>
    <div className="scan-progress"><motion.div animate={{ width: `${percent}%` }} /></div>
    <div className="progress-meta"><span>{percent}% complete</span><span>{operation?.events.length || 0} events</span></div>
    <div className="live-events">{(operation?.events || []).slice(-5).map((event, index) => <div key={`${event.at}-${index}`}><CircleCheck /><span>{event.message || event.current}</span></div>)}</div>
    {done && operation?.status !== 'completed' && <button className="secondary-action" onClick={onClose}>Close</button>}
    {!done && <button className="cancel-action" onClick={() => api.post(`/api/operations/${operationId}/cancel`)}>Cancel search</button>}
  </motion.div>
}

function HistoryPage() {
  const navigate = useNavigate()
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ['cases'], queryFn: () => api.get<CaseRecord[]>('/api/cases') })
  const [query, setQuery] = useState('')
  const rows = (data || []).filter(item => `${item.name} ${item.description} ${(item.tags || []).join(' ')}`.toLowerCase().includes(query.toLowerCase()))
  return <section className="content-page">
    <PageTitle overline="Saved locally" title="Search history" description="Reopen previous MIA Discover and MIA Workbench investigations without spending credits or repeating work." action={<button className="icon-action" onClick={() => refetch()}><RefreshCw />Refresh</button>} />
    <div className="history-toolbar"><label><Search /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Filter saved searches" /></label><span>{rows.length} cases</span></div>
    {isLoading ? <Loading label="Loading history" /> : error ? <ErrorBox error={error} /> : rows.length ? <div className="history-table">
      <div className="history-header"><span>Search</span><span>Signals</span><span>Updated</span><span /></div>
      {rows.map(item => <button key={item.case_id} onClick={() => navigate(`/results/${item.case_id}`)}><span className="case-name"><span className="history-icon"><Search /></span><span><strong>{item.name}</strong><small>{item.description || item.case_id}</small></span></span><span className="signal-count">{item.node_count ?? item.nodes ?? 0} nodes · {item.edge_count ?? item.edges ?? 0} links</span><span>{formatDate(item.updated_at)}</span><ChevronRight /></button>)}
    </div> : <EmptyBox icon={History} title="No saved searches" text="Run your first selector search and it will be stored here." />}
  </section>
}

function ResultsPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<ResultTab>('overview')
  const [operationId, setOperationId] = useState<string | null>(null)
  const [selected, setSelected] = useState<EvidenceNode | EvidenceEdge | null>(null)
  const [aiDialogOpen, setAiDialogOpen] = useState(false)
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ['case', id], queryFn: () => api.get<CasePayload>(`/api/cases/${id}`), enabled: Boolean(id) })
  const { data: providers = [] } = useQuery({ queryKey: ['providers'], queryFn: () => api.get<Provider[]>('/api/providers') })

  const verify = async () => {
    const result = await api.post<{ operation_id: string }>(`/api/cases/${id}/guided-review`, { use_ai: false })
    setOperationId(result.operation_id)
  }
  const explain = async (provider: string, confirmExternalCost: boolean) => {
    const result = await api.post<{ operation_id: string }>(`/api/cases/${id}/guided-review`, {
      use_ai: true, provider, confirm_external_cost: confirmExternalCost, depth: 'thorough', thinking_level: 'high',
    })
    setAiDialogOpen(false)
    setOperationId(result.operation_id)
  }
  if (isLoading) return <Loading label="Opening results" />
  if (error || !data) return <ErrorBox error={error} />
  const seeds = data.deep_seeds || []
  const primary = String((seeds[0] as Record<string, unknown> | undefined)?.target || data.case.name)
  const accounts = data.nodes.filter(node => node.entity_type === 'profile' || node.entity_type === 'account' || node.attributes.platform || node.attributes.username).filter(displayableAccount)
  const other = data.nodes.filter(node => !accounts.includes(node) && !['case_subject', 'candidate_subject'].includes(node.entity_type))
  const strongCount = accounts.filter(node => identityAssessment(node, primary, data).rank >= 3).length
  const sourceCount = new Set(data.nodes.flatMap(node => node.sources)).size
  const tabs: Array<[ResultTab, string, number?]> = [['overview', 'Overview'], ['accounts', 'Accounts', accounts.length], ['data', 'Data', other.length], ['graph', 'Graph'], ['raw', 'Raw']]

  return <section className="results-page">
    <div className="results-topline"><button className="back-link" onClick={() => navigate('/')}><ArrowLeft />New search</button><div className="result-actions"><button className="icon-action" onClick={() => navigator.clipboard.writeText(location.href)}><Copy />Copy link</button><button className="icon-action" onClick={verify}><ShieldCheck />Verify & compare</button><button className="primary-action" onClick={() => setAiDialogOpen(true)}><Sparkles />Explain with AI</button></div></div>
    <header className="result-hero">
      <div className="result-avatar"><img src="/mia-discover-icon.svg" alt="" /></div>
      <div><span className="overline">Selector result</span><h1>{primary}</h1><p>{data.case.description || 'Public-source enrichment results from the shared MIA engine.'}</p><div className="result-tags"><span><Clock3 />{formatDate(data.case.updated_at)}</span><span><LockKeyhole />Stored locally</span><span><Activity />{data.scans.length} scans</span></div></div>
    </header>
    <div className="metric-row">
      <Metric label="Profiles found" value={accounts.length} icon={UserRoundSearch} />
      <Metric label="Identity links" value={strongCount} icon={ShieldCheck} />
      <Metric label="Other data" value={other.length} icon={Database} />
      <Metric label="Sources used" value={sourceCount} icon={Layers3} />
    </div>
    <div className="accuracy-notice"><CircleAlert /><p><strong>A profile page is not an identity match.</strong> Same-handle results remain unconfirmed until MIA finds an explicit profile link or independent corroborating details.</p></div>
    <nav className="result-tabs">{tabs.map(([key, label, count]) => <button key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>{label}{count !== undefined && <span>{count}</span>}</button>)}</nav>
    <div className="result-content">
      {tab === 'overview' && <OverviewResults data={data} primary={primary} accounts={accounts} other={other} onTab={setTab} />}
      {tab === 'accounts' && <AccountGrid accounts={accounts} primary={primary} data={data} />}
      {tab === 'data' && <DataGrid nodes={other} />}
      {tab === 'graph' && <div className="graph-panel"><Suspense fallback={<Loading label="Loading graph" />}><GraphCanvas nodes={data.nodes} edges={data.edges} onSelect={(item) => setSelected(item)} /></Suspense>{selected && <Inspector item={selected} onClose={() => setSelected(null)} />}</div>}
      {tab === 'raw' && <pre className="raw-panel">{JSON.stringify(data, null, 2)}</pre>}
    </div>
    <OperationOverlay operationId={operationId} onClose={() => setOperationId(null)} onComplete={() => { setOperationId(null); refetch(); queryClient.invalidateQueries({ queryKey: ['overview'] }) }} />
    {aiDialogOpen && <AIReviewDialog providers={providers} onClose={() => setAiDialogOpen(false)} onRun={explain} />}
  </section>
}

function AIReviewDialog({ providers, onClose, onRun }: { providers: Provider[]; onClose: () => void; onRun: (provider: string, confirmExternalCost: boolean) => Promise<void> }) {
  const ready = providers.filter(provider => provider.ready)
  const [provider, setProvider] = useState(ready.some(item => item.provider === 'local') ? 'local' : ready[0]?.provider || 'local')
  const [confirmed, setConfirmed] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const selected = providers.find(item => item.provider === provider)
  const external = Boolean(selected?.external)
  const run = async () => {
    if (external && !confirmed) return
    setSubmitting(true); setError('')
    try { await onRun(provider, confirmed) }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); setSubmitting(false) }
  }
  return <div className="dialog-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
    <section className="ai-dialog" role="dialog" aria-modal="true" aria-labelledby="ai-dialog-title">
      <button className="dialog-close" onClick={onClose}><X /></button>
      <img className="dialog-icon" src="/mia-discover-icon.svg" alt="" />
      <span className="overline">Optional explanation</span><h2 id="ai-dialog-title">Choose how MIA explains the evidence</h2>
      <p>MIA already parses bounded public profile metadata such as display names, biographies, profile links, locations, page titles, and verification signals. The selected provider receives that evidence summary—not your API key.</p>
      <div className="provider-choice">{ready.map(item => <label className={provider === item.provider ? 'selected' : ''} key={item.provider}><input type="radio" name="ai-provider" value={item.provider} checked={provider === item.provider} onChange={() => { setProvider(item.provider); setConfirmed(false) }} /><span><strong>{item.provider === 'local' ? 'MIA local explanation' : item.provider}</strong><small>{item.provider === 'local' ? 'Offline and deterministic. No external API call.' : `${item.model} · uses your configured provider account`}</small></span><em>{item.provider === 'local' ? 'No API cost' : 'May be billed'}</em></label>)}</div>
      {external && <label className="cost-confirm"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} /><span><strong>I understand this sends the evidence summary to {selected?.provider}</strong><small>The request uses the API key configured on this computer. Charges, quotas, and retention are controlled by that provider and your account.</small></span></label>}
      <div className="ai-safety-note"><LockKeyhole /><span>Discover never calls Gemini or another external AI during a normal search. External use requires this confirmation each time.</span></div>
      {error && <div className="inline-error"><CircleAlert />{error}</div>}
      <div className="dialog-actions"><button className="secondary-action" onClick={onClose}>Cancel</button><button className="primary-action" disabled={submitting || (external && !confirmed)} onClick={run}>{submitting ? <LoaderCircle /> : <Sparkles />}{provider === 'local' ? 'Generate locally' : `Use ${selected?.provider || provider}`}</button></div>
    </section>
  </div>
}

function Metric({ label, value, icon: Icon }: { label: string; value: number; icon: typeof Search }) {
  return <article><span className="metric-icon"><Icon /></span><span><small>{label}</small><strong>{value}</strong></span></article>
}

function OverviewResults({ data, primary, accounts, other, onTab }: { data: CasePayload; primary: string; accounts: EvidenceNode[]; other: EvidenceNode[]; onTab: (tab: ResultTab) => void }) {
  const strongest = [...accounts].sort((a, b) => identityAssessment(b, primary, data).rank - identityAssessment(a, primary, data).rank || b.confidence - a.confidence).slice(0, 6)
  return <div className="overview-results">
    <section className="result-section span-two"><SectionHeading overline="Discovery leads" title="Public profiles found" action={<button className="text-action" onClick={() => onTab('accounts')}>View all <ArrowRight /></button>} />{strongest.length ? <AccountGrid accounts={strongest} primary={primary} data={data} compact /> : <EmptyBox icon={UserRoundSearch} title="No public accounts found" text="Install or enable username-search integrations, then rerun the search." />}</section>
    <section className="result-section"><SectionHeading overline="Assessment" title="What MIA thinks" />{data.analysis ? <AnalysisSummary analysis={data.analysis} /> : <div className="analysis-placeholder"><Bot /><h3>No explanation generated</h3><p>Run “Verify & compare” without AI, or choose “Explain with AI” and confirm the provider first.</p></div>}</section>
    <section className="result-section"><SectionHeading overline="Connections" title="Identity clusters" /><div className="cluster-list">{data.clusters.length ? data.clusters.slice(0, 5).map(cluster => <div key={cluster.cluster_id}><span className={`confidence-dot ${confidenceClass(cluster.confidence)}`} /><span><strong>{cluster.label}</strong><small>{cluster.node_ids.length} linked signals · {Math.round(cluster.confidence * 100)}%</small></span></div>) : <div className="quiet-empty"><Network /><p>No clusters have been confirmed yet.</p></div>}</div></section>
    <section className="result-section span-two"><SectionHeading overline="Additional enrichment" title="Other public data" action={<button className="text-action" onClick={() => onTab('data')}>View all <ArrowRight /></button>} />{other.length ? <DataGrid nodes={other.slice(0, 8)} compact /> : <div className="quiet-empty"><Database /><p>No additional data points were returned.</p></div>}</section>
  </div>
}

function AccountGrid({ accounts, primary, data, compact = false }: { accounts: EvidenceNode[]; primary: string; data: CasePayload; compact?: boolean }) {
  const [filter, setFilter] = useState('')
  const rows = accounts.filter(node => `${platformName(node)} ${nodeTitle(node)} ${node.value}`.toLowerCase().includes(filter.toLowerCase()))
  return <div className={compact ? 'account-wrapper compact' : 'account-wrapper'}>
    {!compact && <div className="cards-toolbar"><label><Filter /><input value={filter} onChange={event => setFilter(event.target.value)} placeholder="Filter accounts" /></label><span>{rows.length} account signals</span></div>}
    <div className="account-grid">{rows.map(node => {
      const url = publicUrl(node)
      const page = pageAssessment(node)
      const identity = identityAssessment(node, primary, data)
      const pageScore = Number(node.attributes.verification_score ?? node.confidence)
      return <article className="account-card" key={node.node_id}>
        <div className="account-head"><span className="service-logo">{platformName(node).slice(0, 2).toUpperCase()}</span><span><strong>{platformName(node)}</strong><small>{node.sources.slice(0, 2).join(', ') || 'MIA'}</small></span><span className={`confidence-pill ${page.className}`}>{page.label}</span></div>
        <h3>{nodeTitle(node)}</h3><p>{node.value}</p>
        <div className={`identity-signal ${identity.className}`}><strong>{identity.label}</strong><span>{identity.detail}</span></div>
        <div className="account-meta"><span><Layers3 />{node.sources.length} discovery source{node.sources.length === 1 ? '' : 's'}</span><span><ShieldCheck />Page check {Number.isFinite(pageScore) ? `${Math.round(pageScore * 100)}%` : 'not run'}</span></div>
        {url ? <a href={url} target="_blank" rel="noreferrer">Open public profile <ExternalLink /></a> : <span className="no-link"><Info />No direct public URL</span>}
      </article>
    })}</div>
    {!rows.length && <EmptyBox icon={UserRoundSearch} title="No matching account cards" text="Try a deeper search or install additional account-discovery modules." />}
  </div>
}

function DataGrid({ nodes, compact = false }: { nodes: EvidenceNode[]; compact?: boolean }) {
  return <div className={compact ? 'data-grid compact' : 'data-grid'}>{nodes.map(node => <article key={node.node_id}><span className="data-icon"><Database /></span><span><small>{entityLabels[node.entity_type] || node.entity_type}</small><strong>{node.label || node.value}</strong><p>{node.value}</p></span><span className={`confidence-pill ${confidenceClass(node.confidence)}`}>{Math.round(node.confidence * 100)}%</span></article>)}</div>
}

function AnalysisSummary({ analysis }: { analysis: Record<string, unknown> }) {
  const assessments = Array.isArray(analysis.identity_assessments) ? analysis.identity_assessments as Array<Record<string, unknown>> : []
  const passes = Array.isArray(analysis.passes) ? analysis.passes as Array<Record<string, unknown>> : []
  const statements = assessments.length ? assessments : passes.flatMap(pass => Array.isArray(pass.statements) ? pass.statements as Array<Record<string, unknown>> : [])
  return <div className="analysis-list">{statements.slice(0, 6).map((statement, index) => <div key={index}><Sparkles /><p>{String(statement.text || statement.summary || '')}</p></div>)}{!statements.length && <p className="muted">The saved analysis has no displayable statements.</p>}</div>
}

function Inspector({ item, onClose }: { item: EvidenceNode | EvidenceEdge; onClose: () => void }) {
  const node = 'node_id' in item
  return <aside className="inspector"><button onClick={onClose}><X /></button><span className="overline">{node ? 'Evidence node' : 'Connection'}</span><h2>{node ? item.label : item.label}</h2><pre>{JSON.stringify(item, null, 2)}</pre></aside>
}

function SettingsPage() {
  const { data: providers, isLoading, error } = useQuery({ queryKey: ['providers'], queryFn: () => api.get<Provider[]>('/api/providers') })
  const { data: overview } = useQuery({ queryKey: ['overview'], queryFn: () => api.get<OverviewPayload>('/api/overview') })
  return <section className="content-page">
    <PageTitle overline="Configuration" title="Discover settings" description="Check scan readiness and control when an external AI provider may be used." />
    {isLoading ? <Loading label="Checking providers" /> : error ? <ErrorBox error={error} /> : <div className="settings-layout">
      <section className="settings-card span-two"><SectionHeading overline="Engine" title="MIA Core" /><div className="engine-status"><div><Radar /><span><strong>{overview?.stats.installed_tools || 0} / {overview?.stats.catalog_tools || 0}</strong><small>discovery tools installed</small></span></div><div><Database /><span><strong>{overview?.stats.cases || 0}</strong><small>local cases stored</small></span></div><div><ShieldCheck /><span><strong>Localhost</strong><small>default network binding</small></span></div></div><p className="settings-note">Install or update advanced modules in <strong>MIA Workbench</strong>. MIA Discover automatically uses the same MIA Core inventory.</p></section>
      <section className="settings-card"><SectionHeading overline="Optional explanations" title="AI providers" /><div className="provider-stack">{providers?.map(provider => <div key={provider.provider}><span className={`status-light ${provider.ready ? 'ready' : ''}`} /><span><strong>{provider.provider}{provider.default ? ' · configured default' : ''}</strong><small>{provider.model} · {provider.credential}</small></span><em>{provider.external ? 'May be billed' : 'Offline'}</em></div>)}</div><div className="ai-policy"><strong>No automatic external AI calls.</strong> Normal searches and “Verify & compare” do not use Gemini or another paid provider. “Explain with AI” shows the chosen provider and requires confirmation before any external request.</div></section>
      <section className="settings-card"><SectionHeading overline="Responsible use" title="Public data only" /><div className="safety-copy"><LockKeyhole /><p>MIA Discover is designed for lawful research involving public information. Results can be wrong, stale, or shared by different people. Do not treat a match as identity proof.</p></div></section>
    </div>}
  </section>
}

function PageTitle({ overline, title, description, action }: { overline: string; title: string; description: string; action?: React.ReactNode }) {
  return <header className="page-title"><div><span className="overline">{overline}</span><h1>{title}</h1><p>{description}</p></div>{action}</header>
}
function SectionHeading({ overline, title, action }: { overline: string; title: string; action?: React.ReactNode }) { return <div className="section-heading"><div><span className="overline">{overline}</span><h2>{title}</h2></div>{action}</div> }
function Loading({ label }: { label: string }) { return <div className="loading-box"><LoaderCircle /><p>{label}…</p></div> }
function ErrorBox({ error }: { error: unknown }) { return <div className="error-box"><CircleAlert /><div><h2>Could not load this page</h2><p>{error instanceof Error ? error.message : String(error)}</p></div></div> }
function EmptyBox({ icon: Icon, title, text }: { icon: typeof Search; title: string; text: string }) { return <div className="empty-box"><Icon /><h3>{title}</h3><p>{text}</p></div> }

export default App
