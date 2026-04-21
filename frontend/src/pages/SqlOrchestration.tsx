import { useEffect, useRef, useState } from 'react'
import { OrchestrationApi, type Orchestration, type OrchestrationExecution, type LogEntry } from '../api/orchestration'
import { SqlApi, type DataSource, type SqlFile } from '../api/sql'
import { FlowEditor } from '../components/orchestration/FlowEditor'
import { useOrchestrationEditor } from '../components/orchestration/hooks/useOrchestrationEditor'

const EMPTY_ORCH: Orchestration = { id: '', name: '', description: '', nodes: [], edges: [], createdAt: 0, updatedAt: 0 }

export default function SqlOrchestration() {
  const [orchestrations, setOrchestrations] = useState<Orchestration[]>([])
  const [datasources, setDatasources] = useState<DataSource[]>([])
  const [sqlFiles, setSqlFiles] = useState<SqlFile[]>([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<Orchestration | null>(null)
  const [saving, setSaving] = useState(false)
  const [executing, setExecuting] = useState(false)
  const [execution, setExecution] = useState<OrchestrationExecution | null>(null)
  const [error, setError] = useState('')
  const logPanelRef = useRef<HTMLDivElement>(null)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)

  const editorHook = useOrchestrationEditor(editing ?? EMPTY_ORCH)

  const load = async () => {
    try {
      const [orchs, ds, files] = await Promise.all([OrchestrationApi.list(), SqlApi.listDataSources(), SqlApi.listSqlFiles()])
      setOrchestrations(orchs); setDatasources(ds); setSqlFiles(files)
    } catch { setError('加载数据失败') }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])
  useEffect(() => {
    if (execution && logPanelRef.current) logPanelRef.current.scrollIntoView({ behavior: 'smooth' })
  }, [execution])

  // Used by list view and Part 4 integration
  void datasources; void sqlFiles
  const startEditing = (orch: Orchestration) => {
    setEditing(orch)
    setExecution(null)
    setError('')
    setSelectedNodeId(null)
    editorHook.resetFrom(orch)
  }
  void startEditing

  // ─── Save / Execute ───────────────────────────────────

  const handleSave = async () => {
    if (!editing) return
    setSaving(true); setError('')
    try {
      const payload = editorHook.toPayload()
      if (editing.id) {
        const u = await OrchestrationApi.update(editing.id, { ...editing, ...payload })
        setEditing(u)
        editorHook.resetFrom(u)
      } else {
        const c = await OrchestrationApi.create({ name: editing.name, description: editing.description })
        const u = await OrchestrationApi.update(c.id, { ...editing, ...payload })
        setEditing(u)
        editorHook.resetFrom(u)
      }
      await load()
    } catch { setError('保存失败') }
    finally { setSaving(false) }
  }

  const handleExecute = async () => {
    if (!editing?.id) return
    try { await handleSave() } catch { /* auto-save */ }
    setExecuting(true); setExecution(null); setError('')
    try {
      const { executionId } = await OrchestrationApi.execute(editing.id)
      while (true) {
        const p = await OrchestrationApi.progress(editing.id, executionId)
        setExecution({
          id: executionId, orchestrationId: editing.id, orchestrationName: editing.name,
          status: p.status, logs: p.logs, startTime: p.startTime, endTime: p.endTime,
        })
        if (p.status !== 'running') break
        await new Promise(r => setTimeout(r, 1000))
      }
      const final = await OrchestrationApi.progress(editing.id, executionId)
      setExecution({
        id: executionId, orchestrationId: editing.id, orchestrationName: editing.name,
        status: final.status, logs: final.logs, startTime: final.startTime, endTime: final.endTime ?? Date.now(),
      })
      if (final.status === 'failed') setError('编排执行失败')
      else if (final.status === 'warning') setError('编排执行完成，但有阈值警告')
    } catch (e) { setError(e instanceof Error ? e.message : '执行失败') }
    finally { setExecuting(false) }
  }

  const handleStop = async () => {
    if (!editing?.id) return
    try {
      await OrchestrationApi.stop(editing.id)
      setError('正在停止...')
    } catch { setError('停止失败') }
  }

  const handleDelete = async (id: string) => {
    try { await OrchestrationApi.delete(id); if (editing?.id === id) setEditing(null); await load() }
    catch { setError('删除失败') }
  }

  // ─── Render ───────────────────────────────────────────

  if (loading) return <div className="page"><p>加载中...</p></div>

  if (editing) return (
    <div className="page orch-editor-page">
      <div className="orch-page-header">
        <div className="page-header-left">
          <button className="chip" onClick={() => { setEditing(null); setExecution(null); setError('') }}>&larr; 返回</button>
          <input className="orch-name-input" type="text" placeholder="编排名称" value={editing.name}
            onChange={e => setEditing({ ...editing, name: e.target.value })} />
        </div>
        <div className="page-header-right">
          <button className="chip" onClick={() => editorHook.addNode('sql')}>+ SQL</button>
          <button className="chip" onClick={() => editorHook.addNode('debug')}>+ Debug</button>
          <button className="chip" onClick={() => editorHook.addNode('load')}>+ 加载</button>
          <button className="chip" onClick={() => editorHook.addNode('wait')}>+ Wait</button>
          <button className="chip primary" onClick={handleSave} disabled={saving}>{saving ? '保存中...' : '保存'}</button>
          {editing.id && !executing && <button className="chip accent" onClick={handleExecute}>执行</button>}
          {editing.id && executing && <button className="chip danger" onClick={handleStop}>停止</button>}
        </div>
      </div>
      {error && <div className="orch-error">{error}</div>}

      <FlowEditor
        orch={editing}
        selectedNodeId={selectedNodeId}
        onSelectNode={setSelectedNodeId}
        editorHook={editorHook}
      />

      {/* Log panel */}
      {execution && (
        <div className="orch-log-panel" ref={logPanelRef}>
          <div className="orch-log-header">
            <h3>执行日志</h3>
            <span className={`orch-status-badge ${execution.status}`}>
              {execution.status === 'success' ? '成功' : execution.status === 'failed' ? '失败' : execution.status === 'running' ? '执行中' : '警告'}
            </span>
            {execution.endTime ? <span className="orch-log-duration">{((execution.endTime - execution.startTime) / 1000).toFixed(1)}s</span> : <span className="orch-log-duration">执行中...</span>}
          </div>
          <div className="orch-log-entries">
            {execution.logs.map(log => <LogEntryCard key={log.nodeId} log={log} />)}
          </div>
        </div>
      )}
    </div>
  )

  // ─── List view ────────────────────────────────────────
  return (
    <div className="page">
      <div className="orch-page-header">
        <h1>SQL 编排</h1>
        <button className="chip primary"
          onClick={() => setEditing({ id: '', name: '', description: '', nodes: [], edges: [], createdAt: 0, updatedAt: 0 })}>
          + 新建编排
        </button>
      </div>
      {orchestrations.length === 0 ? (
        <div className="sql-var-empty card"><p>暂无编排</p></div>
      ) : (
        <div className="orch-list">
          {orchestrations.map(orch => (
            <div key={orch.id} className="orch-card card">
              <div className="orch-card-header">
                <h3>{orch.name}</h3>
                <span className="orch-node-count">{orch.nodes.length} 节点</span>
              </div>
              {orch.description && <p className="orch-card-desc">{orch.description}</p>}
              <div className="orch-card-nodes">
                {orch.nodes.map(node => <span key={node.id} className={`orch-mini-node ${node.type}`}>{node.name}</span>)}
              </div>
              <div className="orch-card-actions">
                <button className="chip" onClick={() => { setEditing(orch); setExecution(null); setError('') }}>编辑</button>
                <button className="chip danger" onClick={() => handleDelete(orch.id)}>删除</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Log Entry ──────────────────────────────────────────────

function LogEntryCard({ log }: { log: LogEntry }) {
  const [expanded, setExpanded] = useState(true)
  const icons: Record<string, string> = { success: '\u2713', failed: '\u2717', warning: '\u26A0', skipped: '\u2014', running: '\u23F3' }
  return (
    <div className={`orch-log-entry ${log.status}`} onClick={() => setExpanded(!expanded)}>
      <div className="orch-log-entry-header">
        <span className={`orch-log-status-icon ${log.status === 'running' ? 'spin' : ''}`}>{icons[log.status]}</span>
        <span className="orch-log-node-name">{log.nodeName}</span>
        <span className={`orch-node-type-badge small ${log.nodeType}`}>{log.nodeType === 'sql' ? 'SQL' : log.nodeType === 'debug' ? 'Debug' : log.nodeType === 'load' ? '加载' : '等待'}</span>
        <span className="orch-log-duration">{log.status === 'running' ? '等待中...' : `${(log.duration / 1000).toFixed(2)}s`}</span>
        {log.nodeType === 'debug' && log.thresholdPassed !== undefined && (
          <span className={`orch-threshold-result ${log.thresholdPassed ? 'pass' : 'fail'}`}>
            {log.thresholdPassed ? '通过' : '未通过'}
          </span>
        )}
      </div>
      {expanded && (
        <div className="orch-log-entry-body">
          <div className="orch-log-sql"><label>SQL:</label><code>{log.sql}</code></div>
          {log.affectedRows !== undefined && <div className="orch-log-detail"><label>影响行数:</label><span>{log.affectedRows}</span></div>}
          {log.result && (
            <div className="orch-log-detail"><label>结果:</label>
              <div className="orch-log-result-table"><table>
                <thead><tr>{log.result.columns.map(c => <th key={c}>{c}</th>)}</tr></thead>
                <tbody>{log.result.rows.map((row, i) => <tr key={i}>{log.result!.columns.map(c => <td key={c}>{String(row[c] ?? '')}</td>)}</tr>)}</tbody>
              </table></div>
            </div>
          )}
          {log.nodeType === 'debug' && log.actualValue !== undefined && (
            <div className="orch-log-detail">
              <label>实际值:</label><span>{log.actualValue}</span>
              {log.expectedValue !== undefined && <><span className="orch-log-sep">|</span><label>期望:</label><span>{log.expectedValue}</span></>}
            </div>
          )}
          {log.nodeType === 'wait' && log.actualValue !== undefined && (
            <div className="orch-log-detail">
              <label>数据条数:</label><span>{log.actualValue}</span>
              {log.expectedValue !== undefined && <><span className="orch-log-sep">|</span><span>{log.expectedValue}</span></>}
            </div>
          )}
          {log.error && <div className="orch-log-error"><label>错误:</label><span>{log.error}</span></div>}
        </div>
      )}
    </div>
  )
}
