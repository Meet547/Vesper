import test from 'node:test';
import assert from 'node:assert/strict';
import { agentChatLine, agentChatStatuses, agentChatStatus } from '../frontend/assets/agent-chat.mjs';
import { beginInvestigation, createInvestigationState, reduceInvestigationEvent } from '../frontend/assets/agent-state.mjs';

test('waiting messages follow the real dependency order and reset on retry', () => {
  const idle = createInvestigationState();
  assert.ok(agentChatStatuses(idle).every(row => row.text === 'Ready for a case.'));
  const running = beginInvestigation(idle, '730000004');
  assert.match(agentChatStatus(running, 'Tracer'), /waiting for Scout/);
  assert.match(agentChatStatus(running, 'Reporter'), /waiting for Skeptic/);
  const started = reduceInvestigationEvent(running, { agent: 'Scout', stage: 'validating', status: 'started' }).state;
  assert.match(agentChatStatus(started, 'Scout'), /checking the seed/);
  assert.equal(beginInvestigation(started, '730000005').transcript.length, 0);
});

test('chat dialogue uses confirmed event data and structured handoffs', () => {
  let state = beginInvestigation(createInvestigationState(), '730000004');
  for (const raw of [
    { agent: 'Scout', stage: 'validating', status: 'started' },
    { agent: 'Scout', stage: 'graph_search', status: 'completed' },
    { agent: 'Scout', event_name: 'agent_handoff', stage: 'context_handoff', status: 'completed',
      message: 'Seed validated; trace directed paths within the configured hop limit.',
      handoff: { from: 'Scout', to: 'Tracer', type: 'seed_context', evidence_ids: ['tx:730000004'] } },
    { agent: 'Tracer', stage: 'graph_search', status: 'completed', path_count: 2 },
  ]) state = reduceInvestigationEvent(state, raw).state;
  const lines = state.transcript.map(item => agentChatLine(item, state.seed));
  assert.match(lines[0].text, /seed 730000004/);
  assert.match(lines[2].text, /passed the case update to Tracer/);
  assert.match(lines[3].text, /2 directed path/);
  assert.equal(lines.some(line => /recent suspicious|criminal/i.test(line.text)), false);
});

test('missing model interpretation stays visible after the report completes', () => {
  let state = beginInvestigation(createInvestigationState(), '730000005');
  state = reduceInvestigationEvent(state, { agent: 'Analyst', stage: 'agent_reasoning', status: 'warning' }).state;
  assert.match(agentChatLine(state.transcript.at(-1)).text, /unavailable/);
  state = reduceInvestigationEvent(state, { agent: 'Reporter', stage: 'report_completed', status: 'completed' }).state;
  assert.match(agentChatStatus(state, 'Analyst'), /unavailable/);
  assert.match(agentChatStatus(state, 'Reporter'), /finished the evidence report/);
});
