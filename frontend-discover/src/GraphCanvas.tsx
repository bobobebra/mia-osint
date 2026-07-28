import { useEffect, useRef, useState } from 'react'
import cytoscape, { type Core, type EdgeSingular, type NodeSingular } from 'cytoscape'
import { Maximize2, Search, SlidersHorizontal } from 'lucide-react'
import type { EvidenceEdge, EvidenceNode } from './types'

const colors: Record<string, string> = {
  username: '#a78bfa', email: '#38bdf8', domain: '#34d399', profile: '#fb7185', ip: '#f59e0b',
  person: '#f472b6', phone: '#22d3ee', company: '#facc15', url: '#60a5fa', address: '#c084fc',
  candidate_subject: '#e879f9', case_subject: '#ffffff', hash: '#94a3b8', certificate: '#2dd4bf',
}

export default function GraphCanvas({ nodes, edges, onSelect }: {
  nodes: EvidenceNode[]
  edges: EvidenceEdge[]
  onSelect: (item: EvidenceNode | EvidenceEdge, type: 'node' | 'edge') => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const instance = useRef<Core | null>(null)
  const [query, setQuery] = useState('')
  const [minConfidence, setMinConfidence] = useState(0)

  useEffect(() => {
    if (!container.current) return
    instance.current?.destroy()
    const visible = nodes.filter(n => n.confidence >= minConfidence && (!query || `${n.label} ${n.value} ${n.entity_type}`.toLowerCase().includes(query.toLowerCase())))
    const ids = new Set(visible.map(n => n.node_id))
    const graphEdges = edges.filter(e => ids.has(e.source_node_id) && ids.has(e.target_node_id))
    const cy = cytoscape({
      container: container.current,
      elements: [
        ...visible.map(n => ({ data: { id: n.node_id, label: n.label, type: n.entity_type, confidence: n.confidence, payload: n } })),
        ...graphEdges.map(e => ({ data: { id: e.edge_id, source: e.source_node_id, target: e.target_node_id, label: e.label, confidence: e.confidence, payload: e } })),
      ],
      style: [
        { selector: 'node', style: { 'background-color': (ele: NodeSingular) => colors[String(ele.data('type'))] || '#64748b', label: 'data(label)', color: '#dce7ff', 'font-size': 10, 'text-outline-color': '#08101e', 'text-outline-width': 2, 'text-valign': 'bottom', 'text-margin-y': 8, width: (ele: NodeSingular) => 24 + Number(ele.data('confidence')) * 22, height: (ele: NodeSingular) => 24 + Number(ele.data('confidence')) * 22, 'border-width': 2, 'border-color': '#ffffff35', 'overlay-opacity': 0 } },
        { selector: 'node:selected', style: { 'border-width': 4, 'border-color': '#ffffff' } },
        { selector: 'edge', style: { width: (ele: EdgeSingular) => 1 + Number(ele.data('confidence')) * 2.5, 'line-color': '#6b7c9d80', 'target-arrow-color': '#6b7c9d80', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier', label: 'data(label)', color: '#8191ae', 'font-size': 8, 'text-background-color': '#09111f', 'text-background-opacity': .8, 'text-background-padding': 3, 'text-rotation': 'autorotate' } },
        { selector: 'edge:selected', style: { 'line-color': '#60a5fa', 'target-arrow-color': '#60a5fa', width: 4 } },
      ] as any,
      layout: { name: visible.length > 80 ? 'cose' : 'cose', animate: true, animationDuration: 700, padding: 50, nodeRepulsion: () => 9000, idealEdgeLength: () => 110 },
      minZoom: .15,
      maxZoom: 3,
    })
    cy.on('tap', 'node', event => onSelect(event.target.data('payload'), 'node'))
    cy.on('tap', 'edge', event => onSelect(event.target.data('payload'), 'edge'))
    instance.current = cy
    return () => cy.destroy()
  }, [nodes, edges, query, minConfidence, onSelect])

  return <div className="graph-shell">
    <div className="graph-toolbar glass">
      <label><Search size={16}/><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Filter graph"/></label>
      <label className="confidence-control"><SlidersHorizontal size={16}/><span>{Math.round(minConfidence * 100)}%</span><input type="range" min="0" max="1" step=".05" value={minConfidence} onChange={e => setMinConfidence(Number(e.target.value))}/></label>
      <button className="icon-button" onClick={() => instance.current?.fit(undefined, 50)} title="Fit graph"><Maximize2 size={17}/></button>
    </div>
    <div ref={container} className="graph-canvas" />
  </div>
}
