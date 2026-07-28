import { useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Check, CircleAlert, LoaderCircle, Square, X } from 'lucide-react'
import type { OperationState } from './types'
import { api } from './api'

export default function OperationModal({ operationId, onClose, onComplete }: {
  operationId: string | null
  onClose: () => void
  onComplete?: (operation: OperationState) => void
}) {
  const [operation, setOperation] = useState<OperationState | null>(null)
  const [connected, setConnected] = useState(false)
  const done = useMemo(() => operation && ['completed', 'failed', 'cancelled'].includes(operation.status), [operation])

  useEffect(() => {
    if (!operationId) return
    let alive = true
    let timer: number | undefined
    const poll = async () => {
      try { const value = await api.get<OperationState>(`/api/operations/${operationId}`); if (alive) setOperation(value) } catch { /* socket may still work */ }
      if (alive) timer = window.setTimeout(poll, 1200)
    }
    poll()
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
    const socket = new WebSocket(`${protocol}://${location.host}/ws/operations/${operationId}`)
    socket.onopen = () => setConnected(true)
    socket.onclose = () => setConnected(false)
    socket.onmessage = event => {
      const payload = JSON.parse(event.data)
      if (payload.type === 'snapshot') setOperation(payload.operation)
      else setOperation(current => current ? { ...current, progress: payload.progress ?? current.progress, current: payload.current ?? current.current, message: payload.message || current.message, events: [...current.events, payload].slice(-300) } : current)
    }
    return () => { alive = false; if (timer) clearTimeout(timer); socket.close() }
  }, [operationId])

  useEffect(() => { if (operation && done) onComplete?.(operation) }, [done, operation, onComplete])
  if (!operationId) return null
  const percent = Math.round((operation?.progress || 0) * 100)
  const statusIcon = operation?.status === 'completed' ? <Check/> : operation?.status === 'failed' ? <CircleAlert/> : <LoaderCircle className="spin"/>
  return <AnimatePresence>
    <motion.div className="modal-backdrop" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}}>
      <motion.div className="operation-modal glass" initial={{opacity:0, y:24, scale:.97}} animate={{opacity:1, y:0, scale:1}} exit={{opacity:0, y:20}}>
        <div className="operation-head">
          <div className={`operation-icon ${operation?.status || 'queued'}`}>{statusIcon}</div>
          <div><span className="eyebrow">{operation?.kind || 'Operation'}</span><h2>{operation?.title || 'Starting…'}</h2></div>
          {done && <button className="icon-button" onClick={onClose}><X/></button>}
        </div>
        <div className="progress-copy"><strong>{operation?.current || 'Preparing'}</strong><span>{percent}%</span></div>
        <div className="progress-track"><motion.div animate={{width:`${percent}%`}} transition={{ease:'easeOut'}}/></div>
        <p className="muted operation-message">{operation?.error || operation?.message || (connected ? 'Connected to live progress' : 'Waiting for live progress…')}</p>
        <div className="event-stream">
          {(operation?.events || []).slice(-7).map((event, index) => <motion.div key={`${event.at}-${index}`} initial={{opacity:0,x:-8}} animate={{opacity:1,x:0}}><span>{new Date(event.at).toLocaleTimeString()}</span>{event.message || event.current}</motion.div>)}
        </div>
        {!done && <button className="danger-button subtle" onClick={() => api.post(`/api/operations/${operationId}/cancel`)}><Square size={15}/> Cancel</button>}
        {done && operation?.status === 'completed' && <button className="primary-button wide" onClick={onClose}><Check size={17}/> Done</button>}
        {done && operation?.status !== 'completed' && <button className="secondary-button wide" onClick={onClose}>Close</button>}
      </motion.div>
    </motion.div>
  </AnimatePresence>
}
