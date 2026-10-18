import { AGENT_PERSONAS } from './agent-theatre.mjs';

export const AGENT_IDS = ['Scout', 'Tracer', 'Historian', 'Analyst', 'Skeptic', 'Reporter'];

export function pendingVerificationCount(context = {}) {
  const pending = new Set();
  for (const [index, claim] of (context.unverified_claims || []).entries()) pending.add(`claim:${claim.claim_id || index}`);
  for (const [index, claim] of (context.hypotheses || []).entries()) {
    if (claim.verification === 'unverified') pending.add(`claim:${claim.claim_id || `hypothesis_${index}`}`);
  }
  const resolved = new Set((context.validated_memories || []).filter(memory =>
    ['verified', 'rejected'].includes(memory.verification)).map(memory => memory.case_id));
  for (const memory of context.memory_candidates || []) if (!resolved.has(memory.case_id)) pending.add(`memory:${memory.case_id}`);
  return pending.size;
}

export function finalCaseBoardContext(result = {}) {
  const source = result.shared_context || result.sharedContext || {};
  const context = { ...source };
  const decisions = Array.isArray(result.graph_decisions) ? result.graph_decisions
    : Array.isArray(context.graph_decisions) ? context.graph_decisions : [];
  const currentDecision = context.current_graph_decision?.selected_action
    ? context.current_graph_decision : decisions.at(-1) || {};
  const budget = result.graph_action_budget || currentDecision.graph_action_budget || context.graph_action_budget;
  if (decisions.length) {
    context.graph_decisions = decisions;
    context.current_graph_decision = currentDecision;
  }
  if (budget) context.graph_action_budget = budget;

  const ledgerPaths = result.evidence_ledger?.paths;
  const scope = context.graph_scope || {};
  if ((!Array.isArray(scope.path_details) || !scope.path_details.length) && Array.isArray(ledgerPaths)) {
    context.graph_scope = {
      ...scope,
      path_details: ledgerPaths.map((path, index) => ({
        evidence_id: path.evidence_id || result.traces?.[index]?.evidence_id
          || `path:${path.direction || 'directed'}:${(path.node_ids || []).join('>')}`,
        direction: path.direction,
        hops: path.hop_count,
        node_ids: path.node_ids || [],
        edge_ids: path.edge_ids || [],
        verification: path.valid === true ? 'verified' : 'unverified',
        reason: path.validation_reason,
      })),
    };
  }
  return context;
}

const TASKS = {
  Scout: 'Checking the seed transaction in the selected graph',
  Tracer: 'Traversing directed FLOWS_TO edges within the hop limit',
  Historian: 'Comparing current transaction IDs with saved cases',
  Analyst: 'Preparing a concise interpretation from verified evidence',
  Skeptic: 'Checking paths and claims against deterministic evidence',
  Reporter: 'Assembling verified findings and limitations',
};

const STATE_ON_START = {
  Scout: 'WORKING', Tracer: 'WORKING', Historian: 'READING',
  Analyst: 'THINKING', Skeptic: 'THINKING', Reporter: 'WORKING',
};

function initialAgents(defaultState = 'WAITING') {
  return Object.fromEntries(AGENT_IDS.map(agent => [agent, {
    state: defaultState,
    task: defaultState === 'IDLE' ? 'Ready for the next case' : 'Waiting for assigned evidence work',
    lastMessage: '',
  }]));
}

export function createInvestigationState() {
  return {
    runToken: 0, investigationId: null, seed: '', status: 'idle',
    agents: initialAgents('IDLE'), transcript: [], seen: new Set(), eventCount: 0,
    sharedContext: null, meeting: null,
  };
}

export function beginInvestigation(previous, seed) {
  return {
    runToken: (previous?.runToken || 0) + 1,
    investigationId: null,
    seed: String(seed || ''),
    status: 'running',
    agents: initialAgents('WAITING'),
    transcript: [],
    seen: new Set(),
    eventCount: 0,
    sharedContext: null,
    meeting: null,
  };
}

function handoffFor(raw, agent) {
  if (raw.event_name === 'memory_candidate_found') return { from: 'Historian', to: 'Skeptic', kind: 'case-file' };
  if (raw.event_name === 'memory_verified' || raw.event_name === 'memory_rejected') return { from: 'Skeptic', to: 'Reporter', kind: 'review-card' };
  if (agent === 'Scout' && raw.status === 'completed') return { from: 'Scout', to: 'Tracer', kind: 'seed-card' };
  if (agent === 'Tracer' && raw.status === 'completed') return { from: 'Tracer', to: 'Skeptic', kind: 'evidence-card' };
  if (agent === 'Analyst' && raw.status === 'completed') return { from: 'Analyst', to: 'Skeptic', kind: 'analysis-card' };
  if (agent === 'Skeptic' && raw.stage === 'claim_validation' && raw.status === 'completed') return { from: 'Skeptic', to: 'Reporter', kind: 'verified-card' };
  return null;
}

function userMessage(raw, agent) {
  const status = raw.status;
  const count = value => Number.isFinite(Number(value)) ? Number(value) : 0;
  if (raw.event_name === 'memory_candidate_found') {
    const shared = Array.isArray(raw.shared_transactions) ? raw.shared_transactions.length : 0;
    return `Prior case ${raw.case_id || ''} shares ${shared} transaction ID${shared === 1 ? '' : 's'} with this evidence.`.trim();
  }
  if (raw.event_name === 'memory_verified') return `Prior case ${raw.case_id || ''} passed Skeptic review against current graph evidence.`.trim();
  if (raw.event_name === 'memory_rejected') return `Prior case ${raw.case_id || ''} was excluded after Skeptic review.`.trim();
  if (status === 'started') {
    return AGENT_PERSONAS[agent]?.opening || 'Investigation work started.';
  }
  if (status === 'failed') return raw.message || 'The graph lookup did not complete.';
  if (status === 'warning' && agent === 'Analyst') return 'Model interpretation is unavailable; graph evidence remains intact.';
  if (agent === 'Scout' && status === 'completed') return 'Seed located; dataset label recorded.';
  if (agent === 'Tracer' && status === 'completed') return `${count(raw.path_count)} directed paths returned within the selected hop limit.`;
  if (agent === 'Historian' && status === 'completed') {
    const memories = count(raw.memory_count);
    return memories ? `Found ${memories} prior case candidate${memories === 1 ? '' : 's'} by graph overlap.` : 'No saved case overlaps these transaction IDs.';
  }
  if (agent === 'Skeptic' && status === 'completed') {
    if (raw.stage === 'memory_validation') return `Memory review complete: ${count(raw.verified_memory_count)} verified, ${count(raw.rejected_memory_count)} excluded.`;
    if (raw.stage === 'claim_validation') return `Claim checks complete: ${count(raw.verified)} verified, ${count(raw.rejected)} rejected, ${count(raw.unverified)} unverified.`;
    return 'Path structure checked against current graph evidence.';
  }
  if (agent === 'Analyst' && status === 'completed') return 'Evidence-led interpretation is ready for claim checks.';
  if (agent === 'Reporter' && status === 'completed') return raw.message || 'Evidence-first report ready.';
  return raw.message || `${agent || 'Investigation'} update received.`;
}

export function normalizeInvestigationEvent(raw = {}) {
  const eventName = raw.event_name || '';
  const agent = AGENT_IDS.includes(raw.agent) ? raw.agent : '';
  const isSystemStart = eventName === 'investigation_started';
  const isSystemError = eventName === 'investigation_error';
  const systemEvents = ['shared_context_updated', 'graph_decision', 'agent_handoff', 'context_sync_started',
    'context_sync_completed', 'cross_verification_started', 'cross_verification_completed',
    'meeting_started', 'meeting_completed'];
  if (!agent && !isSystemStart && !isSystemError && !systemEvents.includes(eventName)) return null;
  const state = isSystemStart ? 'WORKING'
    : isSystemError ? 'ERROR'
      : eventName === 'memory_candidate_found' ? 'TALKING'
        : eventName === 'memory_verified' || eventName === 'memory_rejected' ? 'SUCCESS'
          : raw.status === 'started' ? STATE_ON_START[agent]
            : raw.status === 'failed' || (raw.status === 'warning' && eventName !== 'memory_rejected') ? 'ERROR'
              : raw.status === 'completed' || eventName === 'memory_rejected' ? 'SUCCESS' : 'WAITING';
  const signature = [raw.event_id || '', raw.investigation_id || '', eventName || raw.stage || '', agent || 'system', raw.status || '',
    raw.case_id || '', (raw.shared_transactions || []).join(','), raw.memory_count ?? '', raw.path_count ?? '',
    raw.verified ?? '', raw.rejected ?? '', raw.unverified ?? '', raw.meeting_id || '',
    raw.handoff?.type || '', raw.handoff?.from || '', raw.handoff?.to || '',
    (raw.handoff?.evidence_ids || []).join(','), raw.handoff?.timestamp || '',
    raw.graph_decision?.selected_action || '', raw.graph_decision?.selection_reason || '',
    (raw.graph_decision?.graph_evidence_ids || []).slice(0, 20).join(',')].join('|');
  const evidence = {
    pathCount: raw.path_count,
    memoryCount: raw.memory_count,
    sharedTransactions: Array.isArray(raw.shared_transactions) ? raw.shared_transactions.slice(0, 8) : [],
    supportingEvidenceIds: Array.isArray(raw.supporting_evidence_ids) ? raw.supporting_evidence_ids.slice(0, 8) : [],
    caseId: raw.case_id || '',
  };
  return {
    signature, eventName, agent, state,
    status: raw.status || '', stage: raw.stage || '',
    message: isSystemStart ? `Investigation ${raw.investigation_id || ''} started.`.trim()
      : isSystemError ? (raw.message || 'Investigation failed. You can retry.')
        : eventName === 'graph_decision' ? `${raw.graph_decision?.selected_action || 'Graph action'}: ${raw.graph_decision?.selection_reason || raw.message || 'Evidence-based action selected.'}`.slice(0, 240)
          : systemEvents.includes(eventName) ? String(raw.message || 'Shared context updated.').slice(0, 240)
          : userMessage(raw, agent),
    evidence,
    timestamp: raw.timestamp || new Date().toISOString(),
    investigationId: raw.investigation_id || '',
    handoff: raw.handoff || (agent && !raw.shared_context ? handoffFor(raw, agent) : null),
    sharedContext: raw.shared_context || null,
    meeting: ['meeting_started', 'meeting_completed'].includes(eventName) ? {
      id: raw.meeting_id || '', participants: Array.isArray(raw.meeting_participants) ? raw.meeting_participants : [],
      focus: raw.meeting_focus || raw.message || '', active: eventName === 'meeting_started',
    } : null,
    terminal: isSystemError || (agent === 'Reporter' && raw.status === 'completed' &&
      ['completed', 'report_completed'].includes(raw.stage)),
  };
}

export function appendTranscript(previous, event, limit = 80) {
  const item = {
    eventName: event.eventName, agent: event.agent || 'Vesper', message: event.message,
    status: event.status, stage: event.stage, handoff: event.handoff,
    evidence: event.evidence, timestamp: event.timestamp || new Date().toISOString(),
  };
  return [...(previous || []), item].slice(-Math.max(1, limit));
}

export function reduceInvestigationEvent(previous, raw = {}) {
  const state = previous || createInvestigationState();
  if (raw.runToken != null && raw.runToken !== state.runToken) return { state, event: null, accepted: false };
  if (state.status === 'complete' || state.status === 'error') return { state, event: null, accepted: false };
  const event = normalizeInvestigationEvent(raw);
  if (!event || state.seen.has(event.signature)) return { state, event: null, accepted: false };
  if (state.investigationId && event.investigationId && state.investigationId !== event.investigationId) {
    return { state, event: null, accepted: false };
  }
  const seen = new Set(state.seen);
  seen.add(event.signature);
  if (seen.size > 300) seen.delete(seen.values().next().value);
  const transcript = appendTranscript(state.transcript, event, 80);
  const agents = { ...state.agents };
  if (!event.agent && event.eventName === 'investigation_error') {
    for (const [name, current] of Object.entries(agents)) {
      if (!['SUCCESS', 'ERROR'].includes(current.state)) {
        agents[name] = { ...current, state: 'ERROR', task: 'Investigation interrupted; ready to retry' };
      }
    }
  } else if (event.agent && !['agent_handoff', 'shared_context_updated'].includes(event.eventName)) {
    const task = event.state === 'SUCCESS' ? 'Work complete; awaiting the next handoff'
      : event.state === 'ERROR' ? 'Check the event message; retry is available'
        : (TASKS[event.agent] || 'Waiting for assigned evidence work');
    agents[event.agent] = { ...agents[event.agent], state: event.state, task, lastMessage: event.message };
    if (event.agent === 'Skeptic' && event.stage === 'memory_validation' && event.status === 'completed') {
      agents.Historian = { ...agents.Historian, state: 'SUCCESS', task: 'Work complete; awaiting the next handoff' };
    }
  }
  const status = event.eventName === 'investigation_error' ? 'error'
    : event.terminal ? 'complete' : (event.eventName === 'investigation_started' ? 'running' : state.status);
  return {
    state: {
      ...state,
      investigationId: event.investigationId || state.investigationId,
      status, agents, transcript, seen, eventCount: state.eventCount + 1,
      sharedContext: event.eventName === 'investigation_error' && state.sharedContext
        ? { ...state.sharedContext, status: 'error', active_agents: [], report_status: 'unavailable',
          current_objective: 'Check the seed and service status before retrying.',
          current_focus: event.message, next_expected_agent: null,
          memory_lookup_status: state.sharedContext.memory_lookup_status === 'complete' ? 'complete' : 'not_completed',
          next_actions: ['Check the seed and service status, then retry the read-only preview.'] }
        : (event.sharedContext || state.sharedContext),
      meeting: event.terminal ? null : event.meeting ? { ...event.meeting } : state.meeting,
    },
    event,
    accepted: true,
  };
}
