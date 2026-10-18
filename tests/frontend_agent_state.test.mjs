import test from 'node:test';
import assert from 'node:assert/strict';
import {
  appendTranscript,
  beginInvestigation,
  createInvestigationState,
  finalCaseBoardContext,
  normalizeInvestigationEvent,
  pendingVerificationCount,
  reduceInvestigationEvent,
} from '../frontend/assets/agent-state.mjs';
import { AGENT_PERSONAS, IDLE_ROUTINES, REQUIRED_CHARACTER_STATES, SPRITE_CLIP_LAYOUT, SPRITE_STATE_MAP, canTakeIdleBreak, nextIdleAgent, nextIdleVisit, spriteBounds, spriteBoundsFromMetadata, spriteFitsOffice, validateSpriteCatalog } from '../frontend/assets/agent-theatre.mjs';

function apply(state, event) {
  return reduceInvestigationEvent(state, { runToken: state.runToken, ...event });
}

test('final Case Board context restores decision budget and evidence omitted from the shared snapshot', () => {
  const result = {
    shared_context: { seed_transaction: 'seed', graph_decisions: [], graph_scope: { paths: ['path:0'] } },
    graph_decisions: [{ selected_action: 'trace_downstream', agent_responsible: 'Tracer', selection_reason: 'Verified frontier.' }],
    graph_action_budget: { limit: 16, used: 4, remaining: 12, exhausted: false },
    evidence_ledger: { paths: [{ path_index: 0, direction: 'downstream', hop_count: 1,
      node_ids: ['seed', 'next'], edge_ids: ['seed->next'], valid: true, evidence_id: 'path:downstream:seed>next' }] },
  };
  const context = finalCaseBoardContext(result);
  assert.equal(context.current_graph_decision.selected_action, 'trace_downstream');
  assert.equal(context.graph_action_budget.remaining, 12);
  assert.deepEqual(context.graph_scope.path_details[0].node_ids, ['seed', 'next']);
  assert.equal(context.graph_scope.path_details[0].verification, 'verified');
});

test('new frontend sessions begin idle and transcript append caps old entries', () => {
  const initial = createInvestigationState();
  assert.equal(initial.status, 'idle');
  assert.equal(initial.agents.Scout.state, 'IDLE');
  const items = Array.from({ length: 3 }, (_, index) => ({ agent: 'Scout', message: String(index) }));
  const result = appendTranscript(items.slice(0, 2), { agent: 'Reporter', message: 'done', timestamp: '2026-10-16T00:00:00.000Z' }, 2);
  assert.deepEqual(result.map(item => item.message), ['1', 'done']);
  assert.equal(items.length, 3);
});

test('normalizes real stage events to safe task summaries and handoffs', () => {
  const scout = normalizeInvestigationEvent({ agent: 'Scout', stage: 'validating', status: 'started' });
  assert.equal(scout.state, 'WORKING');
  assert.match(scout.message, /Quick scan/);
  const tracer = normalizeInvestigationEvent({ agent: 'Tracer', stage: 'graph_search', status: 'completed', path_count: 15 });
  assert.match(tracer.message, /15 directed paths/);
  assert.deepEqual(tracer.handoff, { from: 'Tracer', to: 'Skeptic', kind: 'evidence-card' });
  assert.equal(normalizeInvestigationEvent({ agent: 'LLM', status: 'thinking', message: 'hidden chain' }), null);
});

test('supports concurrent work without overwriting another active agent', () => {
  let state = beginInvestigation(createInvestigationState(), '730000005');
  state = apply(state, { event_name: 'investigation_started', investigation_id: 'inv_a', status: 'started' }).state;
  state = apply(state, { investigation_id: 'inv_a', agent: 'Skeptic', stage: 'claim_validation', status: 'started' }).state;
  state = apply(state, { investigation_id: 'inv_a', agent: 'Historian', stage: 'memory_lookup', status: 'started' }).state;
  assert.equal(state.agents.Skeptic.state, 'THINKING');
  assert.equal(state.agents.Historian.state, 'READING');
});

test('duplicate stream events are idempotent', () => {
  let state = beginInvestigation(createInvestigationState(), '730000005');
  const event = { investigation_id: 'inv_a', agent: 'Tracer', stage: 'graph_search', status: 'completed', elapsed_ms: 51, path_count: 15 };
  state = apply(state, event).state;
  const duplicate = apply(state, event);
  assert.equal(duplicate.accepted, false);
  assert.equal(duplicate.state.transcript.length, 1);
});

test('late events from a prior retry are ignored', () => {
  let state = beginInvestigation(createInvestigationState(), '730000004');
  const priorToken = state.runToken;
  state = beginInvestigation(state, '730000002');
  const late = reduceInvestigationEvent(state, {
    runToken: priorToken, investigation_id: 'old', agent: 'Reporter', stage: 'completed', status: 'completed',
  });
  assert.equal(late.accepted, false);
  assert.equal(late.state.seed, '730000002');
  assert.equal(late.state.transcript.length, 0);
});

test('final report state ignores any late intermediate event', () => {
  let state = beginInvestigation(createInvestigationState(), '730000002');
  state = apply(state, { event_name: 'investigation_started', investigation_id: 'inv_a', status: 'started' }).state;
  state = apply(state, { investigation_id: 'inv_a', agent: 'Reporter', stage: 'completed', status: 'completed' }).state;
  const late = apply(state, { investigation_id: 'inv_a', agent: 'Analyst', stage: 'agent_reasoning', status: 'warning' });
  assert.equal(state.status, 'complete');
  assert.equal(late.accepted, false);
  assert.equal(late.state.agents.Analyst.state, 'WAITING');
});

test('retry starts a clean session with no stale events or report state', () => {
  let state = beginInvestigation(createInvestigationState(), '730000004');
  state = apply(state, { investigation_id: 'inv_a', agent: 'Scout', stage: 'validating', status: 'started' }).state;
  const retry = beginInvestigation(state, '730000005');
  assert.equal(retry.seed, '730000005');
  assert.equal(retry.runToken, state.runToken + 1);
  assert.equal(retry.status, 'running');
  assert.equal(retry.transcript.length, 0);
  assert.equal(retry.agents.Scout.state, 'WAITING');
});

test('Skeptic completion closes Historian after the memory validation handoff', () => {
  let state = beginInvestigation(createInvestigationState(), '730000002');
  state = reduceInvestigationEvent(state, {
    event_name: 'memory_candidate_found', status: 'started', agent: 'Historian',
    case_id: 'case_demo', shared_transactions: ['730000002', '730000004'],
  }).state;
  assert.equal(state.agents.Historian.state, 'TALKING');
  state = reduceInvestigationEvent(state, {
    event_name: 'agent_reasoning', stage: 'memory_validation', status: 'completed', agent: 'Skeptic',
    verified_memory_count: 1, rejected_memory_count: 0,
  }).state;
  assert.equal(state.agents.Historian.state, 'SUCCESS');
});

test('investigation failure marks waiting agents as error and retry resets them', () => {
  let state = beginInvestigation(createInvestigationState(), 'missing-seed');
  state = reduceInvestigationEvent(state, { event_name: 'investigation_error', message: 'Seed not found' }).state;
  assert.equal(state.status, 'error');
  assert.ok(Object.values(state.agents).every(agent => agent.state === 'ERROR'));
  state = beginInvestigation(state, '730000005');
  assert.ok(Object.values(state.agents).every(agent => agent.state === 'WAITING'));
});

test('each agent voice has a distinct, short, evidence-safe opening line', () => {
  const lines = Object.entries(AGENT_PERSONAS).map(([agent, persona]) => {
    const event = normalizeInvestigationEvent({ agent, status: 'started' });
    assert.equal(event.message, persona.opening);
    assert.ok(event.message.length < 100);
    assert.doesNotMatch(event.message, /chain.of.thought|I know|criminal/i);
    return event.message;
  });
  assert.equal(new Set(lines).size, 6);
});

test('idle choreography rotates deterministically and never overrides active work', () => {
  const states = Object.fromEntries(Object.keys(IDLE_ROUTINES).map(id => [id, { state: 'IDLE' }]));
  states.investigationState = 'idle';
  assert.deepEqual(nextIdleAgent(Object.keys(IDLE_ROUTINES), states, 0), { id: 'Scout', nextCursor: 1 });
  states.Scout.moving = true;
  assert.deepEqual(nextIdleAgent(Object.keys(IDLE_ROUTINES), states, 0), { id: 'Tracer', nextCursor: 2 });
  states.investigationState = 'running';
  assert.equal(nextIdleAgent(Object.keys(IDLE_ROUTINES), states, 0), null);
  assert.equal(canTakeIdleBreak({ investigationState: 'idle', agentState: 'WORKING' }), false);
  assert.equal(canTakeIdleBreak({ investigationState: 'idle', agentState: 'IDLE', paused: true }), false);
});

test('sprite anchor boxes use full frame bounds and reject edge clipping', () => {
  const bounds = spriteBounds(40, 140, 80, 136, 135 / 136);
  assert.ok(Math.abs(bounds.left - 0.294) < 0.01);
  assert.equal(bounds.bottom, 140);
  assert.equal(spriteFitsOffice(bounds), true);
  assert.equal(spriteFitsOffice(spriteBounds(20, 140, 80, 136, 135 / 136)), false);
  assert.equal(spriteFitsOffice(spriteBounds(400, 848, 80, 136, 135 / 136)), true);
});

test('every agent has valid full-frame source mappings for all required character states', () => {
  assert.equal(validateSpriteCatalog().valid, true);
  assert.equal(Object.keys(SPRITE_STATE_MAP).length, 6);
  for (const [agent, states] of Object.entries(SPRITE_STATE_MAP)) {
    assert.deepEqual(Object.keys(states), [...REQUIRED_CHARACTER_STATES]);
    for (const mapping of Object.values(states)) {
      const pose = mapping.sourcePose;
      const clip = SPRITE_CLIP_LAYOUT[pose];
      assert.ok(clip, `${agent} references a known crop`);
      assert.ok(clip.frameWidth > 0 && clip.frameHeight > 0 && clip.frames > 0);
    }
  }
  assert.equal(SPRITE_STATE_MAP.Scout.SITTING_FRONT.sourcePose, 'idleF');
  assert.equal(SPRITE_STATE_MAP.Scout.SITTING_FRONT.flipX, false);
});

test('sitting frame metadata aligns its actual 90px full crop at the feet anchor', () => {
  const meta = { frameWidth: 80, frameHeight: 90, anchorX: 40, anchorY: 90,
    visualBounds: { left: 0, top: 0, right: 80, bottom: 90 } };
  const bounds = spriteBoundsFromMetadata(100, 200, meta, 1);
  assert.deepEqual(bounds, { left: 60, top: 110, right: 140, bottom: 200, width: 80, height: 90 });
});

test('each agent cycles through distinct deterministic idle stations', () => {
  assert.deepEqual(nextIdleVisit('Tracer', 0), { station: 'rack', nextCursor: 1 });
  assert.deepEqual(nextIdleVisit('Tracer', 1), { station: 'board', nextCursor: 2 });
  assert.equal(new Set(Object.values(IDLE_ROUTINES).map(r => r.visits[0])).size, 6);
  assert.equal(canTakeIdleBreak({ investigationState: 'running', agentState: 'IDLE' }), false);
  assert.equal(canTakeIdleBreak({ investigationState: 'idle', agentState: 'IDLE', paused: true }), false);
});

test('real meeting/context events update the current run and ignore duplicates or old runs', () => {
  let state = beginInvestigation(createInvestigationState(), '730000005');
  state = apply(state, { event_name: 'investigation_started', investigation_id: 'inv_meeting', status: 'started' }).state;
  const meeting = { investigation_id: 'inv_meeting', event_name: 'meeting_started', meeting_id: 'm1',
    meeting_participants: ['Tracer', 'Historian', 'Skeptic'], meeting_focus: 'Compare paths with memory.',
    shared_context: { current_focus: 'syncing evidence', graph_scope: { paths: ['path:0'] } }, message: 'Sync started.' };
  state = apply(state, meeting).state;
  assert.equal(state.meeting.active, true);
  assert.equal(state.sharedContext.current_focus, 'syncing evidence');
  assert.equal(apply(state, meeting).accepted, false);
  const stale = reduceInvestigationEvent(state, { ...meeting, runToken: state.runToken - 1, event_name: 'meeting_completed' });
  assert.equal(stale.accepted, false);
  state = apply(state, { investigation_id: 'inv_meeting', event_name: 'meeting_completed', meeting_id: 'm1', status: 'completed' }).state;
  assert.equal(state.meeting.active, false);
});

test('graph decision events are distinct and update the Case Board context', () => {
  const state = beginInvestigation(createInvestigationState(), '730000002', 3);
  const first = { event_name: 'graph_decision', agent: 'Vesper', status: 'completed',
    investigation_id: 'inv1', message: 'Selected expand_verified_frontier',
    graph_decision: { selected_action: 'expand_verified_frontier', selection_reason: 'One-hop frontier exists.',
      graph_evidence_ids: ['edge:730000002->730000003'] },
    shared_context: { current_graph_decision: { selected_action: 'expand_verified_frontier' } } };
  const second = { ...first, graph_decision: { selected_action: 'cross_check_path', selection_reason: 'A two-hop path was found.',
      graph_evidence_ids: ['path:downstream:730000002>730000003>730000005'] },
    shared_context: { current_graph_decision: { selected_action: 'cross_check_path' } } };
  const one = apply(state, first), two = apply(one.state, second);
  assert.equal(one.accepted, true);
  assert.equal(two.accepted, true);
  assert.equal(two.state.sharedContext.current_graph_decision.selected_action, 'cross_check_path');
  assert.match(two.state.transcript.at(-1).message, /cross_check_path/);
});

test('structured handoffs preserve their backend message and do not fabricate zero counts', () => {
  let state = beginInvestigation(createInvestigationState(), '730000005');
  const handoff = { event_name: 'agent_handoff', agent: 'Tracer', stage: 'context_handoff', status: 'completed',
    message: '15 directed paths are ready for independent validation.',
    handoff: { from: 'Tracer', to: 'Skeptic', type: 'evidence_handoff', evidence_ids: ['path:0'] },
    shared_context: { graph_scope: { paths: ['path:0'] } } };
  const result = apply(state, handoff);
  assert.equal(result.event.message, handoff.message);
  assert.equal(result.state.agents.Tracer.state, 'WAITING');
  assert.equal(result.state.status, 'running');
  const stage = normalizeInvestigationEvent({ agent: 'Tracer', stage: 'graph_search', status: 'completed', path_count: 15, shared_context: {} });
  assert.equal(stage.handoff, null); // the following structured handoff owns the transfer
  const reporterMessage = 'The graph policy followed verified case case_a memory memory_a at frontier 200.';
  const reporter = normalizeInvestigationEvent({ agent: 'Reporter', stage: 'completed', status: 'completed', message: reporterMessage });
  assert.equal(reporter.message, reporterMessage);
});

test('reporter context updates cannot prematurely finish a run; errors close meetings', () => {
  let state = beginInvestigation(createInvestigationState(), '11');
  state = apply(state, { agent: 'Reporter', event_name: 'agent_handoff', status: 'completed', stage: 'context_handoff',
    handoff: { from: 'Reporter', to: 'Skeptic', type: 'review' } }).state;
  assert.equal(state.status, 'running');
  state = apply(state, { event_name: 'meeting_started', meeting_id: 'meeting1', shared_context: { status: 'running', active_agents: ['Skeptic'] } }).state;
  state = apply(state, { event_name: 'investigation_error', message: 'Stream interrupted' }).state;
  assert.equal(state.meeting, null);
  assert.deepEqual(state.sharedContext.active_agents, []);
  assert.equal(state.sharedContext.report_status, 'unavailable');
});

test('pending verification counts each claim once and retains unresolved memory', () => {
  const context={unverified_claims:[{claim_id:'c1'}],hypotheses:[{claim_id:'c1',verification:'unverified'},
    {claim_id:'c2',verification:'verified'}],memory_candidates:[{case_id:'old1'},{case_id:'old2'}],
    validated_memories:[{case_id:'old1',verification:'rejected'},{case_id:'old2',verification:'unverified'}]};
  assert.equal(pendingVerificationCount(context),2);
});
