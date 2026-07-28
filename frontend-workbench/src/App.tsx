import { lazy, Suspense, useMemo, useState } from 'react'
import { NavLink, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import {
  Activity, Archive, Bot, Boxes, BrainCircuit, BriefcaseBusiness, Check, ChevronRight,
  CircleAlert, Clock3, Database, FileSearch, FolderKanban, Gauge, GitBranch,
  LayoutDashboard, Menu, Network, Package, Plus, RefreshCw, Search, Settings, ShieldCheck,
  Sparkles, Upload, UserSearch, X,
} from 'lucide-react'
import { api } from './api'
const GraphCanvas = lazy(() => import('./GraphCanvas'))
import OperationModal from './OperationModal'
import type { CasePayload, CaseRecord, EvidenceEdge, EvidenceNode, OverviewPayload, PackageTool, Provider, ReviewTask } from './types'

const entityTypes = ['username','email','domain','ip','phone','person','company','address','location','url','hash','certificate','file']

type DraftSeed = { target_type:string; target:string; subject:string; notes:string }

const seedPrefixes: Record<string,string> = {
  '@':'username', username:'username', user:'username', handle:'username',
  email:'email', mail:'email', domain:'domain', website:'domain', site:'domain',
  ip:'ip', phone:'phone', tel:'phone', person:'person', name:'person',
  company:'company', organisation:'company', organization:'company',
  address:'address', location:'location', url:'url', link:'url', hash:'hash',
  certificate:'certificate', cert:'certificate', file:'file',
}

function detectSeed(raw:string): DraftSeed | null {
  const text=raw.trim()
  if(!text)return null
  const prefixed=text.match(/^([a-zA-Z@_-]+)\s*:\s*(.+)$/)
  if(prefixed){
    const key=prefixed[1].toLowerCase()
    if(seedPrefixes[key])return {target_type:seedPrefixes[key],target:prefixed[2].trim(),subject:'',notes:''}
  }
  if(text.startsWith('@')&&text.length>1)return {target_type:'username',target:text.slice(1),subject:'',notes:''}
  if(/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(text))return {target_type:'email',target:text,subject:'',notes:''}
  if(/^https?:\/\//i.test(text))return {target_type:'url',target:text,subject:'',notes:''}
  if(/^(?:\d{1,3}\.){3}\d{1,3}$/.test(text)||text.includes(':')&&/^[0-9a-f:]+$/i.test(text))return {target_type:'ip',target:text,subject:'',notes:''}
  if(/^\+?[\d\s().-]{7,}$/.test(text)&&/[\d]/.test(text))return {target_type:'phone',target:text,subject:'',notes:''}
  if(/^[a-f0-9]{32,128}$/i.test(text))return {target_type:'hash',target:text,subject:'',notes:''}
  if(!text.includes(' ')&&/^[a-z0-9.-]+\.[a-z]{2,}$/i.test(text))return {target_type:'domain',target:text,subject:'',notes:''}
  if(text.includes(' '))return {target_type:'person',target:text,subject:'',notes:''}
  return {target_type:'username',target:text,subject:'',notes:''}
}

function parseSeeds(value:string): DraftSeed[] {
  const seen=new Set<string>()
  return value.split(/[\n]+/).map(detectSeed).filter((item):item is DraftSeed=>{
    if(!item)return false
    const key=`${item.target_type}:${item.target.toLowerCase()}`
    if(seen.has(key))return false
    seen.add(key);return true
  })
}

function accountPlatform(node:EvidenceNode):string {
  if(node.attributes.platform)return String(node.attributes.platform)
  try{return new URL(node.value).hostname.replace(/^www\./,'')}
  catch{return node.sources[0]||'public profile'}
}

function accountUsername(node:EvidenceNode):string {
  if(node.attributes.username)return String(node.attributes.username).replace(/^@/,'')
  const verified=node.attributes.verified_profile
  if(verified&&typeof verified==='object'&&'username' in verified){
    return String((verified as Record<string,unknown>).username||node.label).replace(/^@/,'')
  }
  return node.label.replace(/^@/,'')
}

function App() {
  const [mobileOpen, setMobileOpen] = useState(false)
  return <div className="app-shell">
    <Sidebar open={mobileOpen} onClose={() => setMobileOpen(false)}/>
    <main className="app-main">
      <header className="mobile-header glass"><button className="icon-button" onClick={() => setMobileOpen(true)}><Menu/></button><Logo compact/></header>
      <AnimatePresence mode="wait"><Routes>
        <Route path="/" element={<Page><Overview/></Page>}/>
        <Route path="/cases" element={<Page><Cases/></Page>}/>
        <Route path="/cases/new" element={<Page><NewCase/></Page>}/>
        <Route path="/cases/:id" element={<Page><CaseWorkspace/></Page>}/>
        <Route path="/packages" element={<Page><Packages/></Page>}/>
        <Route path="/settings" element={<Page><SettingsPage/></Page>}/>
        <Route path="*" element={<Navigate to="/" replace/>}/>
      </Routes></AnimatePresence>
    </main>
  </div>
}

function Page({children}:{children:React.ReactNode}) {
  return <motion.div className="page" initial={{opacity:0,y:10}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-8}} transition={{duration:.25}}>{children}</motion.div>
}

function Logo({compact=false}:{compact?:boolean}) {
  return <div className="logo"><div className="logo-mark"><img src="/mia-workbench-icon.svg" alt="" /></div>{!compact&&<div><strong>MIA WORKBENCH</strong><span>Advanced investigation interface</span></div>}</div>
}

function Sidebar({open,onClose}:{open:boolean,onClose:()=>void}) {
  const links = [
    ['/', LayoutDashboard, 'Home'], ['/cases/new', UserSearch, 'Start a search'], ['/cases', FolderKanban, 'My searches'], ['/settings', Bot, 'AI settings'], ['/packages', Package, 'Advanced tools'],
  ] as const
  return <><aside className={`sidebar ${open?'open':''}`}><div className="sidebar-top"><Logo/><button className="icon-button mobile-only" onClick={onClose}><X/></button></div>
    <nav>{links.map(([to,Icon,label])=><NavLink key={to} to={to} end={to==='/' } onClick={onClose} className={({isActive})=>isActive?'active':''}><Icon/><span>{label}</span><ChevronRight className="nav-chevron"/></NavLink>)}</nav>
    <div className="alpha-card"><ShieldCheck/><div><strong>Private on this computer</strong><span>Results are clues, not proof. MIA shows uncertainty and asks you to review important matches.</span></div></div>
  </aside>{open&&<button className="sidebar-scrim" onClick={onClose}/>}</>
}

function PageHeader({eyebrow,title,description,action}:{eyebrow:string,title:string,description:string,action?:React.ReactNode}) {
  return <div className="page-header"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>{action}</div>
}

function Loading({label='Loading workspace…'}:{label?:string}) { return <div className="loading-state"><div className="orbital"><span/><span/><span/></div><p>{label}</p></div> }
function ErrorState({error}:{error:unknown}) { return <div className="empty-state error"><CircleAlert/><h3>Something went wrong</h3><p>{error instanceof Error?error.message:String(error)}</p></div> }
function Empty({icon:Icon=FileSearch,title,description,action}:{icon?:React.ComponentType<{size?:number}>,title:string,description:string,action?:React.ReactNode}) { return <div className="empty-state"><Icon size={34}/><h3>{title}</h3><p>{description}</p>{action}</div> }

function Overview() {
  const navigate=useNavigate()
  const {data,isLoading,error}=useQuery({queryKey:['overview'],queryFn:()=>api.get<OverviewPayload>('/api/overview')})
  if(isLoading)return <Loading label="Opening MIA Workbench…"/>
  if(error||!data)return <ErrorState error={error}/>
  const stats=[
    ['Saved searches',data.stats.open_cases,FolderKanban,'violet'],['Public clues',data.stats.nodes,Search,'blue'],['Need your review',data.stats.pending_reviews,ShieldCheck,'amber'],['Search tools ready',`${data.stats.installed_tools}/${data.stats.catalog_tools}`,Package,'green'],
  ] as const
  const defaultProvider=data.providers.find(p=>p.default)
  return <>
    <section className="welcome-card panel">
      <div className="welcome-copy"><span className="eyebrow">Public account discovery</span><h1>Start with a username or profile link</h1><p>MIA searches public platforms, follows explicit public profile links, tests careful handle variants, and explains which accounts may—or may not—belong together.</p><div className="welcome-actions"><button className="primary-button large" onClick={()=>navigate('/cases/new')}><UserSearch/>Find matching accounts</button><button className="secondary-button large" onClick={()=>navigate('/cases')}><FolderKanban/>Open saved searches</button></div></div>
      <div className="how-it-works"><strong>How it works</strong><ol><li><span>1</span>Tell MIA Workbench what you know</li><li><span>2</span>MIA Core checks and compares public results</li><li><span>3</span>You get a cautious explanation and a review list</li></ol></div>
    </section>
    <section className="stats-grid">{stats.map(([label,value,Icon,tone],index)=><motion.article className={`stat-card ${tone}`} key={label} initial={{opacity:0,y:16}} animate={{opacity:1,y:0}} transition={{delay:index*.05}}><div className="stat-icon"><Icon/></div><div><span>{label}</span><strong>{value}</strong></div></motion.article>)}</section>
    <div className="overview-grid simple-overview">
      <section className="panel wide"><div className="section-head"><div><span className="eyebrow">Continue where you stopped</span><h2>Recent searches</h2></div><button className="text-button" onClick={()=>navigate('/cases')}>See all <ChevronRight/></button></div>
        {data.recent_cases.length?<div className="case-list">{data.recent_cases.slice(0,6).map(c=><CaseRow key={c.case_id} item={c} onClick={()=>navigate(`/cases/${c.case_id}`)}/>)}</div>:<Empty icon={UserSearch} title="Nothing searched yet" description="Add one or several clues and MIA will keep everything together in one saved search." action={<button className="primary-button" onClick={()=>navigate('/cases/new')}>Start your first search</button>}/>}</section>
      <section className="panel friendly-status"><div className="section-head"><div><span className="eyebrow">Explanation mode</span><h2>{defaultProvider?.ready?'Ready to explain':'Basic explanation ready'}</h2></div><Bot/></div><p>{defaultProvider?.ready&&defaultProvider.provider!=='local'?`${defaultProvider.provider} is configured as your default AI. MIA will still require evidence references for every accepted statement.`:'MIA can create a private rule-based explanation now. Configure Gemini or Ollama for a more detailed summary.'}</p><button className="secondary-button wide" onClick={()=>navigate('/settings')}>Check AI settings</button></section>
    </div>
  </>
}

function CaseRow({item,onClick}:{item:CaseRecord,onClick:()=>void}) { return <button className="case-row" onClick={onClick}><div className="case-avatar"><BriefcaseBusiness/></div><div className="case-main"><strong>{item.name}</strong><span>{item.description||'No description'} · updated {new Date(item.updated_at).toLocaleString()}</span></div><div className="case-metrics"><span><Network/>{item.nodes??item.node_count??0}</span><span><GitBranch/>{item.edges??item.edge_count??0}</span>{(item.pending_reviews??item.review_count??0)>0&&<span className="warning"><ShieldCheck/>{item.pending_reviews??item.review_count}</span>}</div><ChevronRight/></button> }

function Cases() {
  const navigate=useNavigate(); const [query,setQuery]=useState('')
  const {data,isLoading,error}=useQuery({queryKey:['cases'],queryFn:()=>api.get<CaseRecord[]>('/api/cases')})
  const filtered=(data||[]).filter(c=>`${c.name} ${c.description} ${c.tags.join(' ')}`.toLowerCase().includes(query.toLowerCase()))
  if(isLoading)return <Loading/>
  if(error)return <ErrorState error={error}/>
  return <><PageHeader eyebrow="Saved searches" title="My searches" description="Your saved searches keep results, notes, and explanations together." action={<button className="primary-button" onClick={()=>navigate('/cases/new')}><Plus/>Start a search</button>}/><div className="toolbar panel"><label className="search-input"><Search/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search cases, tags, descriptions…"/></label><span className="count-pill">{filtered.length} cases</span></div>{filtered.length?<div className="case-grid">{filtered.map((item,index)=><motion.button className="case-card" key={item.case_id} onClick={()=>navigate(`/cases/${item.case_id}`)} initial={{opacity:0,y:15}} animate={{opacity:1,y:0}} transition={{delay:index*.03}}><div className="case-card-top"><span className={`status-badge ${item.status}`}>{item.status}</span><span>{new Date(item.updated_at).toLocaleDateString()}</span></div><h3>{item.name}</h3><p>{item.description||'No description provided.'}</p><div className="tag-row">{item.tags.slice(0,4).map(tag=><span key={tag}>{tag}</span>)}</div><div className="case-card-stats"><span><Network/>{item.node_count}</span><span><GitBranch/>{item.edge_count}</span><span><FileSearch/>{item.scan_count}</span><span><ShieldCheck/>{item.review_count}</span></div></motion.button>)}</div>:<Empty icon={FolderKanban} title="No matching cases" description="Try another search or create a new investigation."/>}</>
}

function NewCase() {
  const navigate=useNavigate()
  const [operationId,setOperationId]=useState<string|null>(null)
  const [name,setName]=useState('')
  const [inputText,setInputText]=useState('')
  const [question,setQuestion]=useState('')
  const [notes,setNotes]=useState('')
  const [showAdvanced,setShowAdvanced]=useState(false)
  const [workflow,setWorkflow]=useState('account-discovery')
  const [profile,setProfile]=useState('default')
  const [verify,setVerify]=useState(true)
  const [pivot,setPivot]=useState(true)
  const [error,setError]=useState('')
  const detected=useMemo(()=>parseSeeds(inputText),[inputText])
  const updateDetected=(index:number,key:string,value:string)=>{
    const rows=detected.map((item,i)=>i===index?{...item,[key]:value}:item)
    setInputText(rows.map(item=>`${item.target_type}: ${item.target}`).join('\n'))
  }
  const removeDetected=(index:number)=>setInputText(detected.filter((_,i)=>i!==index).map(item=>`${item.target_type}: ${item.target}`).join('\n'))
  const submit=async()=>{
    setError('')
    if(!detected.length){setError('Add at least one username, email, name, phone number, or website.');return}
    const caseName=name.trim()||`Search for ${detected[0].target}`
    try{
      const result=await api.post<{operation_id:string}>('/api/cases/deep',{
        name:caseName,description:question.trim(),workflow,profile,verify_profiles:verify,
        enable_pivoting:pivot,max_depth:2,max_targets:75,
        hypotheses:question.trim()?[question.trim()]:[],notes,
        seeds:detected.map(seed=>({...seed,target:seed.target.trim(),subject:seed.subject.trim()||null})),
      })
      setOperationId(result.operation_id)
    }catch(e){setError(e instanceof Error?e.message:String(e))}
  }
  return <>
    <PageHeader eyebrow="Find matching accounts" title="Which account do you already know?" description="Paste a username, @handle, or full TikTok, Instagram, X, YouTube, Reddit, GitHub, or other public profile URL. You can add several clues, one per line."/>
    <div className="simple-builder">
      <section className="panel simple-input-card">
        <div className="step-label"><span>1</span><div><strong>Add the clues</strong><small>One per line. You can mix different types.</small></div></div>
        <textarea className="big-seed-input" value={inputText} onChange={e=>setInputText(e.target.value)} placeholder={`@bobobebra\nhttps://www.tiktok.com/@bobobebra\nhttps://www.instagram.com/bobobebra`} autoFocus/>
        <p className="input-help">A full profile link is best: MIA extracts its handle and preserves the original platform as context. You can also use <code>username: bobobebra</code>.</p>
        {detected.length>0&&<div className="detected-block"><div className="section-head"><div><span className="eyebrow">MIA recognized</span><h2>{detected.length} clue{detected.length===1?'':'s'}</h2></div></div><div className="detected-list">{detected.map((seed,index)=><motion.div layout className="detected-row" key={`${seed.target_type}-${seed.target}-${index}`}><select aria-label="Clue type" value={seed.target_type} onChange={e=>updateDetected(index,'target_type',e.target.value)}>{entityTypes.map(type=><option key={type} value={type}>{type}</option>)}</select><strong>{seed.target}</strong><button className="icon-button danger" onClick={()=>removeDetected(index)} aria-label="Remove clue"><X/></button></motion.div>)}</div></div>}
      </section>
      <section className="panel simple-question-card">
        <div className="step-label"><span>2</span><div><strong>What are you trying to understand?</strong><small>Optional, but it helps the explanation stay focused.</small></div></div>
        <textarea value={question} onChange={e=>setQuestion(e.target.value)} placeholder="Example: Do these accounts appear to belong to the same person?"/>
        <label><span>Search name <small>(optional)</small></span><input value={name} onChange={e=>setName(e.target.value)} placeholder={detected[0]?`Search for ${detected[0].target}`:'MIA will create one automatically'}/></label>
        <button className="advanced-toggle" onClick={()=>setShowAdvanced(v=>!v)}><Settings/>{showAdvanced?'Hide':'Show'} advanced options<ChevronRight className={showAdvanced?'rotate':''}/></button>
        <AnimatePresence initial={false}>{showAdvanced&&<motion.div className="advanced-box" initial={{opacity:0,height:0}} animate={{opacity:1,height:'auto'}} exit={{opacity:0,height:0}}>
          <div className="form-grid"><label><span>Search style</span><select value={workflow} onChange={e=>setWorkflow(e.target.value)}><option value="account-discovery">Find matching accounts</option><option value="identity">Compare supplied identities</option><option value="email-enrichment">Email search</option><option value="domain-recon">Website/domain search</option><option value="timeline">Build a timeline</option></select></label><label><span>Depth</span><select value={profile} onChange={e=>setProfile(e.target.value)}><option value="quick">Quick — exact handle</option><option value="default">Recommended — careful variants</option><option value="deep">Deep — more platforms and variants</option><option value="all">Everything available</option></select></label></div>
          <Toggle checked={verify} onChange={setVerify} title="Check whether profiles are real" description="Filters generic pages and obvious false matches."/>
          <Toggle checked={pivot} onChange={setPivot} title="Follow useful public clues" description="Follows explicit public profile links and searches public handles or contact clues that are discovered."/>
          <label><span>Private notes</span><textarea value={notes} onChange={e=>setNotes(e.target.value)} placeholder="Where the clues came from, limitations, or anything you want to remember."/></label>
        </motion.div>}</AnimatePresence>
        <div className="safety-note simple-safety"><ShieldCheck/><p><strong>MIA does not prove identity.</strong> It separates stronger matches, weak same-handle results, contradictions, and items that need your review.</p></div>
        {error&&<p className="form-error">{error}</p>}
        <button className="primary-button wide jumbo" onClick={submit} disabled={!detected.length}><Search/>Start searching</button>
      </section>
    </div>
    <OperationModal operationId={operationId} onClose={()=>setOperationId(null)} onComplete={op=>{const id=String(op.result?.case_id||'');if(op.status==='completed'&&id)navigate(`/cases/${id}`)}}/>
  </>
}
function Toggle({checked,onChange,title,description}:{checked:boolean,onChange:(v:boolean)=>void,title:string,description:string}) { return <button className="toggle-row" onClick={()=>onChange(!checked)}><span className={`switch ${checked?'on':''}`}><i/></span><div><strong>{title}</strong><span>{description}</span></div></button> }

function CaseWorkspace() {
  const {id=''}=useParams()
  const queryClient=useQueryClient()
  const [tab,setTab]=useState('overview')
  const [operationId,setOperationId]=useState<string|null>(null)
  const [showAdvanced,setShowAdvanced]=useState(false)
  const [selected,setSelected]=useState<{item:EvidenceNode|EvidenceEdge,type:'node'|'edge'}|null>(null)
  const {data,isLoading,error}=useQuery({queryKey:['case',id],queryFn:()=>api.get<CasePayload>(`/api/cases/${id}`),refetchInterval:operationId?2000:false})
  const launch=async(path:string,body?:unknown)=>{const result=await api.post<{operation_id:string}>(path,body);setOperationId(result.operation_id)}
  if(isLoading)return <Loading label="Opening your saved search…"/>
  if(error||!data)return <ErrorState error={error}/>
  const pending=data.review_tasks.filter(t=>t.status==='pending')
  const tabs=[['overview','Summary',Gauge],['graph','Connections',Network],['timeline','Timeline',Clock3],['review',`Needs checking ${pending.length?`(${pending.length})`:''}`,ShieldCheck],['analysis','AI explanation',BrainCircuit],['evidence','Files',Database],['logs','Technical details',Activity]] as const
  return <>
    <div className="case-hero panel"><div><div className="case-breadcrumb"><span>My searches</span><ChevronRight/>{data.case.case_id}</div><h1>{data.case.name}</h1><p>{data.case.description||'MIA is comparing the public clues saved in this search.'}</p><div className="tag-row">{data.case.tags.map(tag=><span key={tag}>{tag}</span>)}</div></div><div className="case-actions simple-case-actions"><button className="primary-button jumbo" onClick={()=>launch(`/api/cases/${id}/guided-review`,{use_ai:false})}><ShieldCheck/>Verify and compare</button><button className="secondary-button" onClick={()=>setShowAdvanced(v=>!v)}><Settings/>Advanced</button>{showAdvanced&&<div className="advanced-actions-popover"><button onClick={()=>launch(`/api/cases/${id}/verify`)}><ShieldCheck/>Check profiles only</button><button onClick={()=>launch(`/api/cases/${id}/cluster`)}><GitBranch/>Compare matches only</button><button onClick={()=>setTab('analysis')}><BrainCircuit/>Choose AI options</button></div>}</div></div>
    <div className="friendly-next-step panel"><ShieldCheck/><div><strong>Start with verification</strong><span>“Verify and compare” checks profile pages and contradictions without calling an AI provider. Open the Analysis tab only when you want an optional explanation.</span></div></div>
    <div className="case-tabs">{tabs.map(([key,label,Icon])=><button key={key} className={tab===key?'active':''} onClick={()=>setTab(key)}><Icon/>{label}</button>)}</div>
    <AnimatePresence mode="wait"><motion.div key={tab} initial={{opacity:0,y:8}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-6}} transition={{duration:.2}}>
      {tab==='overview'&&<CaseOverview data={data} onTab={setTab}/>} {tab==='graph'&&<div className="graph-page"><Suspense fallback={<Loading label="Drawing the connections…"/>}><GraphCanvas nodes={data.nodes} edges={data.edges} onSelect={(item,type)=>setSelected({item,type})}/></Suspense>{selected&&<Inspector selected={selected} onClose={()=>setSelected(null)}/>}</div>}
      {tab==='timeline'&&<Timeline events={data.timeline}/>} {tab==='review'&&<ReviewQueue id={id} tasks={data.review_tasks} refresh={()=>queryClient.invalidateQueries({queryKey:['case',id]})}/>} {tab==='analysis'&&<AnalysisPanel id={id} data={data} launch={launch}/>} {tab==='evidence'&&<EvidencePanel id={id} data={data} refresh={()=>queryClient.invalidateQueries({queryKey:['case',id]})}/>} {tab==='logs'&&<RunsPanel scans={data.scans}/>}
    </motion.div></AnimatePresence>
    <OperationModal operationId={operationId} onClose={()=>setOperationId(null)} onComplete={()=>{queryClient.invalidateQueries({queryKey:['case',id]});queryClient.invalidateQueries({queryKey:['overview']})}}/>
  </>
}

function CaseOverview({data,onTab}:{data:CasePayload,onTab:(tab:string)=>void}) {
  const verified=data.verifications.filter(v=>['verified','likely'].includes(String(v.status))).length
  const accounts=data.nodes.filter(node=>node.entity_type==='account'||['profile','web_profile','social_profile'].includes(String(node.attributes.finding_kind||''))).sort((a,b)=>b.confidence-a.confidence)
  const stats=[['Possible accounts',accounts.length,UserSearch],['Relationships',data.edges.length,GitBranch],['Checked profiles',verified,ShieldCheck],['Identity clusters',data.clusters.length,Network]] as const
  return <div className="case-content-grid"><section className="panel span-2"><div className="case-stat-grid">{stats.map(([label,value,Icon])=><div className="mini-stat" key={label}><Icon/><div><strong>{value}</strong><span>{label}</span></div></div>)}</div><div className="section-head"><div><span className="eyebrow">Seed inventory</span><h2>Starting context</h2></div></div><div className="seed-chip-grid">{data.deep_seeds.map((seed,index)=><div className="seed-chip" key={index}><span>{String(seed.target_type)}</span><strong>{String(seed.label||seed.target)}</strong><small>{seed.subject?`Subject: ${String(seed.subject)}`:'Unassigned context'}</small></div>)}</div></section>
    <section className="panel span-2"><div className="section-head"><div><span className="eyebrow">Public account candidates</span><h2>Possible matching accounts</h2></div><button className="text-button" onClick={()=>onTab('graph')}>See connections <ChevronRight/></button></div>{accounts.length?<div className="account-match-grid">{accounts.slice(0,16).map(node=>{const status=String(node.attributes.verification_status||'discovered');const clickable=/^https?:\/\//i.test(node.value);return <a className={`account-match-card ${clickable?'':'disabled'}`} key={node.node_id} href={clickable?node.value:undefined} target={clickable?'_blank':undefined} rel={clickable?'noreferrer':undefined}><div className="account-platform"><UserSearch/><span>{accountPlatform(node)}</span></div><strong>@{accountUsername(node)}</strong><small>{status.replaceAll('_',' ')} · {Math.round(node.confidence*100)}% lead confidence</small>{node.attributes.discovery_method==='explicit_public_profile_link'&&<em>Linked directly from another public profile</em>}</a>})}</div>:<Empty icon={UserSearch} title="No account candidates yet" description="Run a username or public profile-link search with Maigret or Sherlock installed."/>}</section>
    <section className="panel"><div className="section-head"><div><span className="eyebrow">Identity hypotheses</span><h2>Clusters</h2></div><button className="text-button" onClick={()=>onTab('graph')}>Graph <ChevronRight/></button></div>{data.clusters.length?data.clusters.slice(0,5).map(c=><div className="cluster-row" key={c.cluster_id}><div className="confidence-orb" style={{'--score':`${Math.round(c.confidence*100)}%`} as React.CSSProperties}>{Math.round(c.confidence*100)}</div><div><strong>{c.label}</strong><span>{c.node_ids.length} profiles · {c.contradictions.length} contradictions</span></div></div>):<Empty icon={GitBranch} title="No clusters yet" description="Verify candidates and run clustering to form explainable identity hypotheses."/>}</section>
    <section className="panel"><div className="section-head"><div><span className="eyebrow">Human decisions</span><h2>Review queue</h2></div><button className="text-button" onClick={()=>onTab('review')}>Open <ChevronRight/></button></div>{data.review_tasks.filter(t=>t.status==='pending').slice(0,5).map(t=><div className="review-mini" key={t.task_id}><span className={`priority ${t.priority}`}/><div><strong>{t.title}</strong><span>{t.recommended_action||t.description}</span></div></div>)}{!data.review_tasks.some(t=>t.status==='pending')&&<Empty icon={Check} title="Queue is clear" description="No pending manual decisions."/>}</section>
    <section className="panel span-2"><div className="section-head"><div><span className="eyebrow">Case notes</span><h2>Investigator context</h2></div></div><pre className="notes-preview">{data.notes}</pre></section>
  </div>
}

function Inspector({selected,onClose}:{selected:{item:EvidenceNode|EvidenceEdge,type:'node'|'edge'},onClose:()=>void}) { const item=selected.item; const node=selected.type==='node'?item as EvidenceNode:null; const edge=selected.type==='edge'?item as EvidenceEdge:null; return <motion.aside className="inspector glass" initial={{x:30,opacity:0}} animate={{x:0,opacity:1}}><div className="section-head"><div><span className="eyebrow">{selected.type}</span><h2>{node?.label||edge?.label}</h2></div><button className="icon-button" onClick={onClose}><X/></button></div>{node&&<><div className="score-line"><strong>{Math.round(node.confidence*100)}%</strong><span>{node.confidence_label} confidence</span></div><code>{node.value}</code><h3>Sources</h3><div className="tag-row">{node.sources.map(s=><span key={s}>{s}</span>)}</div><h3>Attributes</h3><pre>{JSON.stringify(node.attributes,null,2)}</pre></>}{edge&&<><div className="score-line"><strong>{Math.round(edge.confidence*100)}%</strong><span>{edge.confidence_label} confidence</span></div><h3>Why linked</h3><ul>{edge.reasons.map(r=><li key={r}>{r}</li>)}</ul><h3>Confidence factors</h3>{edge.factors.map((f,i)=><div className="factor" key={i}><span className={f.effect}>{f.effect}</span><strong>{f.label}</strong><small>{f.explanation}</small></div>)}</>}</motion.aside> }

function Timeline({events}:{events:CasePayload['timeline']}) { const grouped=useMemo(()=>events.reduce<Record<string,typeof events>>((acc,e)=>{const year=new Date(e.occurred_at).getFullYear().toString();(acc[year]??=[]).push(e);return acc},{}),[events]); return <section className="panel timeline-panel"><div className="section-head"><div><span className="eyebrow">Chronology</span><h2>Evidence timeline</h2></div><Clock3/></div>{events.length?Object.entries(grouped).sort(([a],[b])=>Number(b)-Number(a)).map(([year,items])=><div className="timeline-year" key={year}><strong>{year}</strong><div>{items.map(item=><article key={item.event_id}><span/><div><time>{new Date(item.occurred_at).toLocaleString()}</time><h3>{item.title}</h3><p>{item.source||item.event_type}</p></div></article>)}</div></div>):<Empty icon={Clock3} title="No dated evidence" description="Verified account dates and other timestamped findings will appear here."/>}</section> }

function ReviewQueue({id,tasks,refresh}:{id:string,tasks:ReviewTask[],refresh:()=>void}) { const mutation=useMutation({mutationFn:({task,status}:{task:string,status:string})=>api.post(`/api/cases/${id}/review/${task}`,{status,note:''}),onSuccess:refresh}); return <section className="panel"><div className="section-head"><div><span className="eyebrow">Manual verification</span><h2>Review queue</h2></div><span className="count-pill">{tasks.filter(t=>t.status==='pending').length} pending</span></div><div className="review-list">{tasks.map(task=><article className={`review-card ${task.status}`} key={task.task_id}><div className={`priority-label ${task.priority}`}>{task.priority}</div><div className="review-body"><h3>{task.title}</h3><p>{task.description}</p>{task.recommended_action&&<div className="recommended"><Sparkles/> {task.recommended_action}</div>}<small>{task.evidence_ids.length} evidence references · {task.task_id}</small></div>{task.status==='pending'?<div className="review-actions"><button onClick={()=>mutation.mutate({task:task.task_id,status:'accepted'})}><Check/>Accept</button><button onClick={()=>mutation.mutate({task:task.task_id,status:'rejected'})}><X/>Reject</button><button onClick={()=>mutation.mutate({task:task.task_id,status:'deferred'})}><Clock3/>Defer</button></div>:<span className="status-badge">{task.status}</span>}</article>)}</div>{!tasks.length&&<Empty icon={ShieldCheck} title="No review tasks" description="Run verification and clustering first."/>}</section> }

function AnalysisPanel({id,data,launch}:{id:string,data:CasePayload,launch:(path:string,body?:unknown)=>void}) { const [provider,setProvider]=useState('local'); const [depth,setDepth]=useState('thorough'); const [thinking,setThinking]=useState('high'); const [confirmed,setConfirmed]=useState(false); const external=provider==='gemini'||provider==='openai-compatible'; const analysis=data.analysis as {passes?:Array<{role:string,statements:Array<{text:string,evidence_ids:string[]}>}>,identity_assessments?:Array<{text:string,evidence_ids:string[]}>} | null; return <div className="analysis-layout"><section className="panel"><span className="eyebrow">Optional explanation</span><h2>Create an evidence-cited explanation</h2><p className="muted">MIA sends bounded parsed profile metadata and case evidence to the provider you choose. A normal scan and “Verify and compare” do not use AI.</p><div className="form-grid single"><label><span>Provider</span><select value={provider} onChange={e=>{setProvider(e.target.value);setConfirmed(false)}}><option value="local">Local deterministic — no API call</option><option value="gemini">Gemini — may use billed quota</option><option value="ollama">Ollama</option><option value="openai-compatible">OpenAI-compatible — may use billed quota</option></select></label><label><span>Depth</span><select value={depth} onChange={e=>setDepth(e.target.value)}>{['quick','standard','thorough','exhaustive'].map(x=><option key={x}>{x}</option>)}</select></label>{provider!=='local'&&<label><span>Thinking level</span><select value={thinking} onChange={e=>setThinking(e.target.value)}>{['minimal','low','medium','high'].map(x=><option key={x}>{x}</option>)}</select></label>}</div>{external&&<label className="external-ai-confirm"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/><span><strong>Confirm external provider use</strong><small>This request uses the API key configured on this computer. Your provider account may apply quota or charges.</small></span></label>}<button className="primary-button wide large" disabled={external&&!confirmed} onClick={()=>launch(`/api/cases/${id}/analyze`,{provider,confirm_external_cost:confirmed,depth,thinking_level:provider==='local'?null:thinking})}><BrainCircuit/>{provider==='local'?'Generate locally':`Use ${provider}`}</button></section><section className="panel analysis-results"><div className="section-head"><div><span className="eyebrow">Latest result</span><h2>Analysis</h2></div><Bot/></div>{analysis?<>{analysis.identity_assessments?.map((s,i)=><article className="analysis-statement" key={i}><p>{s.text}</p><span>Evidence: {s.evidence_ids.join(', ')}</span></article>)}{analysis.passes?.map((pass,i)=><details key={i}><summary>{pass.role} · {pass.statements.length} statements</summary>{pass.statements.map((s,j)=><div className="analysis-statement compact" key={j}><p>{s.text}</p><span>{s.evidence_ids.join(', ')}</span></div>)}</details>)}</>:<Empty icon={BrainCircuit} title="No explanation yet" description="Verify the profiles first, then choose a provider here when an explanation would help."/>}</section></div> }

function EvidencePanel({id,data,refresh}:{id:string,data:CasePayload,refresh:()=>void}) { const [note,setNote]=useState(''); const [kind,setKind]=useState('evidence'); const upload=async(file:File)=>{const form=new FormData();form.append('upload',file);await api.upload(`/api/cases/${id}/attachments?kind=${kind}&note=${encodeURIComponent(note)}`,form);setNote('');refresh()}; return <div className="evidence-layout"><section className="panel"><div className="section-head"><div><span className="eyebrow">Preserve provenance</span><h2>Add evidence</h2></div><Upload/></div><div className="form-grid single"><label><span>Type</span><select value={kind} onChange={e=>setKind(e.target.value)}><option value="evidence">Evidence file</option><option value="screenshot">Screenshot</option></select></label><label><span>Note</span><input value={note} onChange={e=>setNote(e.target.value)} placeholder="Where this came from and why it matters"/></label><label className="upload-zone"><Upload/><strong>Choose a file</strong><span>Up to 50 MiB. MIA records a SHA-256 digest.</span><input type="file" onChange={e=>{const file=e.target.files?.[0];if(file)upload(file)}}/></label></div></section><section className="panel"><div className="section-head"><div><span className="eyebrow">Case store</span><h2>Attachments</h2></div><span className="count-pill">{data.attachments.length}</span></div><div className="attachment-list">{data.attachments.map((item,index)=><div key={index}><Database/><div><strong>{String(item.filename)}</strong><span>{String(item.kind)} · {Math.round(Number(item.size_bytes)/1024)} KiB</span><code>{String(item.sha256)}</code></div></div>)}</div>{!data.attachments.length&&<Empty icon={Database} title="No attachments" description="Add screenshots or files to preserve evidence and provenance."/>}</section></div> }

function RunsPanel({scans}:{scans:Array<Record<string,unknown>>}) { return <section className="panel"><div className="section-head"><div><span className="eyebrow">Execution record</span><h2>Scans and plugin runs</h2></div><Activity/></div>{scans.length?scans.map((scan,index)=><details className="run-detail" key={index}><summary><span>{String(scan.target_type)} · {String(scan.target)}</span><span>{String(scan.scan_id)}</span></summary><pre>{JSON.stringify(scan,null,2)}</pre></details>):<Empty icon={Activity} title="No scans recorded" description="Context-only seeds do not run plugins. Scannable seeds will appear here."/>}</section> }

function Packages() {
  const queryClient=useQueryClient()
  const [query,setQuery]=useState('')
  const [filter,setFilter]=useState('all')
  const [selected,setSelected]=useState<Set<string>>(new Set())
  const [operationId,setOperationId]=useState<string|null>(null)
  const {data,isLoading,error}=useQuery({queryKey:['packages'],queryFn:()=>api.get<{package_manager:string,groups:Record<string,string[]>,tools:PackageTool[]}>('/api/packages')})
  if(isLoading)return <Loading label="Checking package inventory…"/>
  if(error||!data)return <ErrorState error={error}/>
  const tools=data.tools.filter(t=>(
    filter==='all'||
    filter==='installed'&&t.installed||
    filter==='missing'&&!t.installed&&t.platform_supported||
    filter==='unsupported'&&!t.platform_supported||
    filter==='mixed'&&t.risk==='mixed'
  )&&`${t.name} ${t.id} ${t.categories.join(' ')}`.toLowerCase().includes(query.toLowerCase()))
  const run=async(action:string,ids:string[])=>{
    const supported=ids.filter(id=>data.tools.find(tool=>tool.id===id)?.platform_supported)
    if(!supported.length)return
    const result=await api.post<{operation_id:string}>('/api/packages/operations',{action,tools:supported,include_mixed:true})
    setOperationId(result.operation_id)
  }
  const toggle=(tool:PackageTool)=>{
    if(!tool.platform_supported)return
    setSelected(current=>{
      const next=new Set(current)
      if(next.has(tool.id))next.delete(tool.id);else next.add(tool.id)
      return next
    })
  }
  return <>
    <PageHeader eyebrow="OSINT package manager" title="Tools, without dependency chaos" description={`Detected package manager: ${data.package_manager}. Unsupported tools are skipped rather than attempted on this operating system.`} action={<button className="primary-button" disabled={!selected.size} onClick={()=>run('install',[...selected])}><Package/>Install selected ({selected.size})</button>}/>
    <div className="toolbar panel packages-toolbar">
      <label className="search-input"><Search/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder={`Search ${data.tools.length} tools…`}/></label>
      <div className="filter-pills">{['all','installed','missing','unsupported','mixed'].map(x=><button key={x} className={filter===x?'active':''} onClick={()=>setFilter(x)}>{x}</button>)}</div>
    </div>
    <div className="tool-grid">{tools.map(tool=><article className={`tool-card ${selected.has(tool.id)?'selected':''} ${!tool.platform_supported?'unsupported':''}`} key={tool.id}>
      <div className="tool-top">
        <button disabled={!tool.platform_supported} aria-label={`Select ${tool.name}`} className={`check-box ${selected.has(tool.id)?'checked':''}`} onClick={()=>toggle(tool)}>{selected.has(tool.id)&&<Check/>}</button>
        <span className={`status-dot ${tool.installed?'ready':tool.platform_supported?'needs':'unsupported'}`}/>
        <span>{tool.installed?'Installed':tool.platform_supported?'Available':'Unavailable here'}</span>
      </div>
      <div className="tool-icon"><Boxes/></div>
      <h3>{tool.name}</h3><code>{tool.id}</code>
      <div className="tag-row">{tool.categories.slice(0,4).map(c=><span key={c}>{c}</span>)}</div>
      <p><span className={`risk ${tool.risk}`}>{tool.risk}</span> · {tool.integration}</p>
      <small className="platform-detail">{tool.platform_detail}</small>
      <div className="tool-actions">{!tool.platform_supported?<button disabled>Not supported on this OS</button>:tool.installed?<><button onClick={()=>run('update',[tool.id])}><RefreshCw/>Update</button><button className="danger" onClick={()=>run('uninstall',[tool.id])}><Archive/>Remove</button></>:<button className="primary" onClick={()=>run('install',[tool.id])}><Plus/>Install</button>}</div>
    </article>)}</div>
    <OperationModal operationId={operationId} onClose={()=>setOperationId(null)} onComplete={()=>queryClient.invalidateQueries({queryKey:['packages']})}/>
  </>
}

function SettingsPage() { const queryClient=useQueryClient(); const {data,isLoading,error}=useQuery({queryKey:['providers'],queryFn:()=>api.get<Provider[]>('/api/providers')}); const [provider,setProvider]=useState('gemini'); const [model,setModel]=useState(''); const [endpoint,setEndpoint]=useState(''); const [thinking,setThinking]=useState('high'); const [key,setKey]=useState(''); const [message,setMessage]=useState(''); if(isLoading)return <Loading/>; if(error||!data)return <ErrorState error={error}/>; const configure=async()=>{setMessage('');await api.post('/api/providers/configure',{provider,model:model||null,endpoint:endpoint||null,thinking_level:provider==='local'?null:thinking,set_default:true});if(key&&provider!=='local'){const service=provider==='openai-compatible'?'assistant':provider;await api.post('/api/providers/key',{service,value:key});setKey('')}setMessage('Provider settings saved.');queryClient.invalidateQueries({queryKey:['providers']})}; return <><PageHeader eyebrow="Local configuration" title="Assistant and privacy" description="Secrets go to the operating-system keyring, never into case exports or YAML."/><div className="settings-grid"><section className="panel"><div className="section-head"><div><span className="eyebrow">Provider health</span><h2>Available assistants</h2></div><Bot/></div><div className="provider-list">{data.map(item=><article key={item.provider}><span className={`status-dot ${item.ready?'ready':'needs'}`}/><div><h3>{item.provider}{item.default&&<span className="default-pill">default</span>}</h3><p>{item.model} · {item.thinking_level}</p><small>{item.credential}</small></div><span className={`ready-label ${item.ready?'yes':'no'}`}>{item.ready?'Ready':'Configure'}</span></article>)}</div></section><section className="panel"><span className="eyebrow">Configure</span><h2>Assistant provider</h2><div className="form-grid single"><label><span>Provider</span><select value={provider} onChange={e=>setProvider(e.target.value)}>{['local','gemini','ollama','openai-compatible'].map(x=><option key={x}>{x}</option>)}</select></label>{provider!=='local'&&<><label><span>Model</span><input value={model} onChange={e=>setModel(e.target.value)} placeholder={provider==='gemini'?'gemini model ID':'model name'}/></label><label><span>Endpoint override</span><input value={endpoint} onChange={e=>setEndpoint(e.target.value)} placeholder="Leave blank for default"/></label><label><span>Thinking level</span><select value={thinking} onChange={e=>setThinking(e.target.value)}>{['minimal','low','medium','high'].map(x=><option key={x}>{x}</option>)}</select></label><label><span>API key/token</span><input type="password" autoComplete="off" value={key} onChange={e=>setKey(e.target.value)} placeholder="Stored in OS keyring"/></label></>}</div>{message&&<p className="success-message"><Check/>{message}</p>}<button className="primary-button wide" onClick={configure}><Settings/>Save and make default</button></section><section className="panel span-2 privacy-panel"><ShieldCheck/><div><h2>Local-first by default</h2><p>The UI binds to <code>127.0.0.1</code>. Case databases, evidence, screenshots, graph exports, and notes stay on this machine. External AI is opt-in and receives bounded normalized evidence.</p></div></section></div></> }

export default App
