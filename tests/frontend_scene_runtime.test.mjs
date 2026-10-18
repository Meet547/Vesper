import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import * as theatre from '../frontend/assets/agent-theatre.mjs';

const html = await readFile(new URL('../frontend/index.html', import.meta.url), 'utf8');
const data = JSON.parse(html.match(/const D=(.*?);\nconst R=/)[1]);

test('runtime character states use the procedural sprite catalog over the supplied Vesper office artwork', async () => {
  for (const states of Object.values(theatre.SPRITE_STATE_MAP)) for (const mapping of Object.values(states)) {
    const meta = data.meta[mapping.clip];
    assert.equal(meta.w, 80, `${mapping.clip} uses the procedural frame width`);
    assert.equal(meta.h, mapping.clip.endsWith('_sitB') ? 90 : 136);
    assert.equal(meta.n, 1);
  }
  assert.deepEqual(data.assets, {});
  assert.deepEqual(data.bands, []);
  assert.match(html, /function makeSyntheticSceneImage\(key\)/);
  assert.doesNotMatch(html, /bureau-background\.[a-f0-9]+\.webp|bureau-sprites\.[a-f0-9]+\.pack/);
  assert.match(html, /bitmap\.src='\/assets\/vesper-office\.png\?v=20261018-1'/);
  const image = await readFile(new URL('../frontend/assets/vesper-office.png', import.meta.url));
  assert.equal(image.toString('ascii', 1, 4), 'PNG');
  assert.equal(image.readUInt32BE(16), 2528);
  assert.equal(image.readUInt32BE(20), 1696);
  for (const [agent, feet] of Object.entries(theatre.CHAIR_FEET)) {
    const meta = theatre.SPRITE_METADATA.idleB;
    assert.equal(theatre.spriteFitsOffice(theatre.spriteBoundsFromMetadata(...feet, meta)), true, agent);
  }
});

function runtime() {
  const script = html.match(/<script type="module">([\s\S]*?)<\/script>/)[1];
  // Execute the actual office geometry/motion functions, not a second implementation.
  const nav = script.slice(script.indexOf('let k=1'), script.indexOf('const HS='));
  const motion = script.slice(script.indexOf('function moving()'), script.indexOf('function bubble('));
  const update = script.slice(script.indexOf('function upd('), script.indexOf('function frameMetadata('));
  const sandbox = { ...theatre, D: data, window: { devicePixelRatio: 1 }, S: 135/136, CYC: 62,
    scheduleScene() {}, reducedMotion: false, T: 0, console };
  const context = vm.createContext(sandbox);
  vm.runInContext(nav + '\n' + motion + '\n' + update + '\nthis.scene={AG,ST,goSt,interruptMotion,chairTransition,upd,spr,stationTarget,wpath};', context);
  return context.scene;
}

test('desk transitions use one full-body feet anchor and cancellation cannot restore an old pose', async () => {
  const scene = runtime(), actor = scene.AG.find(a => a.id === 'Tracer');
  const original = [actor.x, actor.y];
  actor.routeToken = 1;
  const transition = scene.chairTransition(actor, scene.ST.sB, 1, 1);
  scene.upd(.5);
  assert.equal(actor.x, (original[0] + scene.ST.sB[0]) / 2);
  assert.equal(actor.y, (original[1] + scene.ST.sB[1]) / 2);
  assert.equal(scene.spr(actor).m.h, 136);
  scene.interruptMotion(actor);
  const stopped = [actor.x, actor.y];
  assert.equal(await transition, false);
  scene.upd(1);
  assert.deepEqual([actor.x, actor.y], stopped);
});

test('occupied destinations are separated and stationary agents do not drift', () => {
  const scene = runtime(), actor = scene.AG[0], other = scene.AG[4];
  [other.x, other.y] = scene.ST.rack;
  const target = scene.stationTarget(actor, 'rack');
  assert.ok(Math.hypot(target[0] - other.x, target[1] - other.y) >= 52);
  const positions = scene.AG.map(a => [a.x, a.y]);
  for (let tick = 0; tick < 100; tick++) scene.upd(.016);
  assert.deepEqual(scene.AG.map(a => [a.x, a.y]), positions);
});

test('labels avoid other character bodies and one another at desktop and narrow scales', () => {
  for (const scale of [.3, .75, 1]) {
    const actors = [{id:'Skeptic',x:672,y:626}, {id:'Reporter',x:716,y:724}, {id:'Tracer',x:437,y:568}];
    const items = actors.map(actor => ({id:actor.id,x:actor.x*scale,y:(actor.y-140)*scale,width:52,height:12,
      body:{left:(actor.x-30)*scale,right:(actor.x+30)*scale,top:(actor.y-130)*scale,bottom:actor.y*scale}}));
    const result = theatre.placeOfficeLabels(items, 1264*scale, 848*scale);
    const overlap = (a,b) => a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top;
    for (const label of result) {
      assert.equal(result.some(other=>other!==label&&overlap(label,other)), false);
      assert.equal(items.some(other=>other.id!==label.id&&overlap(label,other.body)), false);
    }
  }
});

test('agent name labels use compact role slots and a pose-independent head anchor', () => {
  const anchor = theatre.officeLabelAnchor('Analyst', 300, 600, 0.5);
  assert.deepEqual(anchor, { x: 161, y: 223.5 });
  assert.deepEqual(theatre.officeLabelAnchor('Analyst', 300, 600, 0.5), anchor);
  assert.deepEqual(theatre.officeLabelAnchor('unknown', 300, 600, 1), { x: 300, y: 460 });
  assert.match(html, /\.bu\{display:none;position:absolute/);
  assert.doesNotMatch(html, /const state=document\.createElement\('small'\);state\.className='agent-state'/);
});

test('seated foreground masks can cover chair-height legs but cannot repaint heads or shoulders', () => {
  const body = theatre.spriteBounds(672,626,80,136,135/136);
  const mask = theatre.furnitureOcclusionBounds(body,true,135/136);
  assert.ok(mask.top>body.top+60);
  assert.ok(mask.top<body.bottom);
  assert.ok(mask.top+mask.height>=body.bottom);
  const walkingMask=theatre.furnitureOcclusionBounds(body,false);
  assert.ok(walkingMask.top<body.top);
});

async function completeRoute(scene, promise) {
  let finished=false,result;
  promise.then(value=>{finished=true;result=value});
  for(let tick=0;tick<8000&&!finished;tick++){
    scene.upd(.05);
    await Promise.resolve();
    for(const actor of scene.AG){
      const bounds=theatre.spriteBounds(actor.x,actor.y,80,136,135/136);
      assert.equal(theatre.spriteFitsOffice(bounds),true,`${actor.id} left the office`);
    }
  }
  assert.equal(finished,true,'route did not settle within the simulation budget');
  return result;
}

test('all six actual office routes reach distinct first break stations and return without teleporting', async () => {
  for(const [agent,routine] of Object.entries(theatre.IDLE_ROUTINES)){
    const scene=runtime(),actor=scene.AG.find(a=>(a.agentKey||a.id)===agent);
    const before=[actor.x,actor.y];
    const route=scene.goSt(actor,routine.visits[0]);
    // A request schedules movement; it cannot immediately move the feet.
    assert.deepEqual([actor.x,actor.y],before);
    assert.equal(await completeRoute(scene,route),true,`${agent} could not reach the break station`);
    assert.equal(await completeRoute(scene,scene.goSt(actor,routine.home)),true,`${agent} could not return`);
  }
});
