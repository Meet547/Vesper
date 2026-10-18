import { AGENT_IDS } from './agent-state.mjs';

const WAITING_FOR = Object.freeze({
  Scout: 'the seed check to begin',
  Tracer: 'Scout to confirm the seed',
  Historian: 'Tracer to provide transaction IDs',
  Analyst: 'Skeptic to check the graph evidence',
  Skeptic: 'Tracer and Historian to provide evidence',
  Reporter: 'Skeptic to finish the independent review',
});

const WORKING = Object.freeze({
  Scout: 'I’m checking the seed in the selected graph.',
  Tracer: 'I’m tracing directed paths within the selected hop limit.',
  Historian: 'I’m checking saved cases for overlapping transaction IDs.',
  Analyst: 'I’m checking whether model interpretation is available for this evidence.',
  Skeptic: 'I’m independently checking paths, memory, and claims.',
  Reporter: 'I’m assembling the evidence report and its limits.',
});

export function agentChatStatus(state, agent) {
  const current = state?.agents?.[agent] || {};
  const work = current.state || 'IDLE';
  if (state?.status === 'idle') return 'Ready for a case.';
  if (state?.status === 'error') return 'This run stopped. Ready to retry.';
  if (state?.status === 'complete') {
    if (agent === 'Analyst' && /unavailable/i.test(current.lastMessage || '')) return 'My model interpretation was unavailable for this case.';
    return agent === 'Reporter' ? 'I finished the evidence report.' : 'My case work is complete.';
  }
  if (work === 'WAITING') return `I’m waiting for ${WAITING_FOR[agent]}.`;
  if (work === 'ERROR') return 'My step could not complete.';
  if (work === 'SUCCESS') return 'My step is complete; the next role has the evidence.';
  return WORKING[agent];
}

export function agentChatLine(item, seed = '') {
  const agent = item?.agent || 'Vesper';
  const status = item?.status;
  const stage = item?.stage;
  const evidence = item?.evidence || {};
  if (item?.eventName === 'agent_handoff' && item.handoff?.from && item.handoff?.to) {
    return { agent: item.handoff.from, text: `I’ve passed the case update to ${item.handoff.to}. ${item.message || ''}`.trim() };
  }
  if (item?.eventName === 'investigation_started') return { agent: 'Vesper', text: `Investigation started for seed ${seed || 'the selected transaction'}.` };
  if (item?.eventName === 'investigation_error') return { agent: 'Vesper', text: item.message || 'The investigation stopped. You can retry.' };
  if (item?.eventName === 'memory_candidate_found') return { agent: 'Historian', text: `I found a prior case with ${evidence.sharedTransactions?.length || 0} shared transaction ID(s). Skeptic will recheck it against this graph.` };
  if (item?.eventName === 'memory_verified') return { agent: 'Skeptic', text: `I rechecked prior case ${evidence.caseId || ''}; its relevant evidence passed current graph review.`.trim() };
  if (item?.eventName === 'memory_rejected') return { agent: 'Skeptic', text: `I excluded prior case ${evidence.caseId || ''} after checking it against current graph evidence.`.trim() };
  if (['shared_context_updated', 'context_sync_started', 'context_sync_completed',
    'cross_verification_started', 'cross_verification_completed', 'meeting_started', 'meeting_completed'].includes(item?.eventName)) {
    return { agent: 'Vesper', text: item.message || 'The shared case context was updated.' };
  }
  if (agent === 'Vesper') return { agent, text: item.message || 'The shared case context was updated.' };
  if (status === 'started') return { agent, text: agent === 'Scout' ? `I’m checking seed ${seed || 'the selected transaction'} in the selected graph.` : WORKING[agent] || item.message };
  if (status === 'failed') return { agent, text: `I couldn’t finish my step. ${item.message || 'Please check the case and retry.'}` };
  if (agent === 'Analyst' && status === 'warning') return { agent, text: 'My model interpretation is unavailable. The verified graph evidence remains available.' };
  if (agent === 'Scout' && status === 'completed') return { agent, text: 'I found the seed and recorded its dataset label.' };
  if (agent === 'Tracer' && status === 'completed') return { agent, text: `I returned ${Number(evidence.pathCount) || 0} directed path(s) within the selected hop limit.` };
  if (agent === 'Historian' && status === 'completed') { const count = Number(evidence.memoryCount) || 0; return { agent, text: count ? `I found ${count} saved case candidate(s) by transaction overlap; Skeptic will verify them.` : 'I found no saved cases with overlapping transaction IDs.' }; }
  if (agent === 'Skeptic' && status === 'completed') return { agent, text: stage === 'memory_validation' ? 'I checked recalled case evidence against the current graph.' : stage === 'claim_validation' ? 'I checked interpretation claims against the evidence ledger.' : 'I checked the returned path structure against the current graph.' };
  if (agent === 'Analyst' && status === 'completed') return { agent, text: 'I prepared interpretation candidates for Skeptic to verify.' };
  if (agent === 'Reporter' && status === 'completed') return { agent, text: 'I assembled the evidence report and its limitations.' };
  return { agent, text: item.message || 'My case update is ready.' };
}

export function agentChatStatuses(state) {
  return AGENT_IDS.map(agent => ({ agent, text: agentChatStatus(state, agent) }));
}
