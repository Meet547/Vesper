import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const html = await readFile(new URL('../frontend/index.html', import.meta.url), 'utf8');

test('guided console keeps primary actions visible and removes redundant scene controls', () => {
  assert.match(html, /<title>Vesper · Bitcoin investigation office<\/title>/);
  assert.match(html, /<h1>Vesper<\/h1>/);
  assert.match(html, /vesper-office\.png\?v=20261018-1/);
  assert.match(html, /id="caseBoard"/);
  assert.match(html, /id="track2Demo"/);
  assert.match(html, /TRACK 2 · GRAPH MEMORY/);
  assert.match(html, /function configureTrackSeeds\(isolated\)/);
  assert.match(html, /\['731000004','731000002','731000001'\]/);
  assert.match(html, /configureTrackSeeds\(!!demo\.enabled\)/);
  assert.doesNotMatch(html, /<title>Bureau|<h1>Bureau<\/h1>/);
  for (const id of ['apiState', 'apiMeta', 'caseLabel', 'seedTxId', 'runInvestigation', 'agentList', 'liveResults', 'channel']) {
    assert.equal((html.match(new RegExp(`id="${id}"`, 'g')) || []).length, 1, `expected one #${id}`);
  }
  assert.match(html, /<details class="advanced-control">\s*<summary>Configure investigation/);
  assert.match(html, /<details class="archive-tools">/);
  assert.match(html, /Start an investigation/);
  assert.match(html, /Quick start example investigations/);
  assert.match(html, /id="openAgentChat"/);
  assert.doesNotMatch(html, /Animation pace|data-sp=|id="kill"|id="mem"|Explore the office/);
  assert.doesNotMatch(html, /<details class="advanced-control" open>/);
  assert.match(html, /REAL GRAPH ACTION/);
  assert.match(html, /DIRECTED PATH EVIDENCE/);
  assert.match(html, /path_details/);
});

test('report names evidence, memory, interpretation, review, and limitations separately', () => {
  for (const section of ['WHAT WAS INVESTIGATED', 'VERIFIED GRAPH EVIDENCE', 'SKEPTIC REVIEW', 'MODEL CLAIM CHECKS', 'Model interpretation', 'Related case memory', 'Limits of this result']) {
    assert.ok(html.includes(section), `missing report section ${section}`);
  }
});

test('small viewports and reduced-motion have explicit layout and behavior rules', () => {
  assert.match(html, /@media\(max-width:820px\)/);
  assert.match(html, /@media\(max-width:520px\)/);
  assert.match(html, /prefers-reduced-motion:reduce/);
  assert.match(html, /function spr\(a\).*i=reducedMotion\?0:/);
  assert.match(html, /function scheduleIdleChoreography\(ms=7000\).*INVEST\.status==='running'/);
});

test('shared case board and developer-only sprite QA remain distinct from normal judge UI', () => {
  assert.match(html, /id="caseBoard"/);
  assert.match(html, /id="meetingBanner"/);
  assert.match(html, /function renderCaseBoard\(context\)/);
  assert.match(html, /function openSpriteDebug\(\)/);
  assert.match(html, /get\('spriteDebug'\)==='1'/);
  assert.match(html, /meeting_started/);
  assert.match(html, /meeting_completed/);
  assert.match(html, /shared_context/);
});

test('Track 2 comparison renders the backend Reporter explanation and paired policy choices', () => {
  assert.match(html, /id="track2Demo"[^>]*aria-label="Track 2 isolated graph memory demonstration"/);
  assert.match(html, /memory_enabled=UI\.track2Demo\.memoryEnabled/);
  assert.match(html, /reporterOutput=r\.structured_report\?\.memory_policy_explanation/);
  assert.match(html, /Paired policy comparison: memory-on first selected frontier/);
  assert.doesNotMatch(html, /Reporter · Skeptic revalidated saved case/);
  assert.match(html, /Reporter explanation/);
  assert.match(html, /@media\(max-width:520px\)\{\.track2-result\{grid-template-columns:minmax\(0,1fr\)\}/);
});
