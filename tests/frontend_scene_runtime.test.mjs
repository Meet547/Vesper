import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import * as theatre from '../frontend/assets/agent-theatre.mjs';

const html = await readFile(new URL('../frontend/index.html', import.meta.url), 'utf8');
const data = JSON.parse(html.match(/const D=(.*?);\nconst R=/)[1]);

test('runtime character states use distinct restored Vesper sprite clips over the supplied office artwork', async () => {
  const pack = await readFile(new URL('../frontend/assets/vesper-characters.b7bb881d9bbe56aa.pack', import.meta.url));
  const clips = new Set();
  for (const [agent, states] of Object.entries(theatre.SPRITE_STATE_MAP)) for (const mapping of Object.values(states)) {
    const meta = data.meta[mapping.clip];
    const pose = mapping.sourcePose;
    assert.equal(meta.w, 80, `${agent}.${mapping.clip} frame width`);
    assert.equal(meta.h, pose === 'sitB' ? 90 : 136);
    assert.equal(meta.n, theatre.SPRITE_CLIP_LAYOUT[pose].frames);
    const asset = data.assets[`clip:${mapping.clip}`];
    assert.ok(asset, `${agent}.${mapping.clip} has a bundled source clip`);
    const bytes = pack.subarray(asset.offset, asset.offset + asset.length);
    assert.equal(bytes.toString('ascii', 1, 4), 'PNG');
    assert.equal(bytes.readUInt32BE(16), meta.w * meta.n);
    assert.equal(bytes.readUInt32BE(20), meta.h);
    clips.add(mapping.clip);
  }
  assert.equal(clips.size, 30, 'each role has distinct walk, idle, and talk clips');
  assert.equal(Object.keys(data.assets).length, 36, 'the bundle also retains authored sitting clips for QA and future pose mapping');
  assert.ok(data.bands.length >= 8, 'walking characters receive depth-aware office furniture masks');
  assert.ok(data.bands.every(band => Array.isArray(band.p) && band.p.length >= 3 && Number.isFinite(band.d)));
  assert.match(html, /const DEPTH_BANDS=D\.bands\.filter/);
  assert.match(html, /g\.imageSmoothingEnabled=false/);
  assert.equal(new Set(Object.values(data.nav.st)).size, Object.keys(data.nav.st).length, 'named Vesper stations have unique map coordinates');
  assert.doesNotMatch(html, /function makeSyntheticSceneImage\(key\)/);
  assert.match(html, /fetch\(PACK_URL/);
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
  vm.runInContext(nav + '\n' + motion + '\n' + update + '\nthis.scene={AG,ST,goSt,toSeat,standUp,walkToPoint,interruptMotion,chairTransition,upd,spr,stationTarget,wpath,ok,cl,near,ctr,NAV_BLOCKERS,DEPTH_BANDS};', context);
  return context.scene;
}

test('desk exits use the nearest clear tile and cancellation cannot restore an old pose', async () => {
  const scene = runtime(), actor = scene.AG.find(a => a.id === 'Tracer');
  const original = [actor.x, actor.y];
  const [i,j] = scene.near(...original), exit = scene.ctr(i,j);
  actor.routeToken = 1;
  const transition = scene.standUp(actor, 1);
  scene.upd(.14);
  assert.ok(Math.hypot(actor.x-original[0],actor.y-original[1])>0);
  assert.ok(Math.hypot(actor.x-exit[0],actor.y-exit[1])<Math.hypot(exit[0]-original[0],exit[1]-original[1]));
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
  assert.ok(Math.hypot(target[0] - other.x, target[1] - other.y) >= 64);
  const positions = scene.AG.map(a => [a.x, a.y]);
  for (let tick = 0; tick < 100; tick++) scene.upd(.016);
  assert.deepEqual(scene.AG.map(a => [a.x, a.y]), positions);
});

test('office navigation avoids furniture and snaps station approaches to clear floor tiles', () => {
  const scene = runtime();
  for (const polygon of scene.NAV_BLOCKERS) {
    const [x, y] = polygon[0], [i, j] = [Math.floor(x / data.nav.C), Math.floor(y / data.nav.C)];
    assert.equal(scene.ok(i, j), false, `furniture footprint ${x},${y} is blocked`);
  }
  for (const station of Object.values(scene.ST)) {
    const target = scene.stationTarget(scene.AG[0], Object.keys(scene.ST).find(name => scene.ST[name] === station));
    assert.ok(target, 'every named station has a reachable floor approach');
    const [i, j] = [Math.floor(target[0] / data.nav.C), Math.floor(target[1] / data.nav.C)];
    assert.equal(scene.ok(i, j), true, `station approach ${target} is on clear floor`);
  }
});

test('server towers use separate depth masks so one rack cannot hide a whole cluster', () => {
  const scene = runtime(), racks = scene.DEPTH_BANDS.filter(band => band.id.startsWith('server-rack-'));
  assert.equal(racks.length, 3);
  assert.deepEqual(racks.map(band => band.d), [423, 453, 505]);
  assert.equal(new Set(racks.map(band => JSON.stringify(band.p))).size, 3);
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
      if(actor.mode==='walk')assert.equal(scene.ok(...scene.cl(actor.x,actor.y)),true,`${actor.id} crossed a blocked furniture tile at ${actor.x},${actor.y}`);
      for(const other of scene.AG)if(other!==actor)assert.ok(Math.hypot(actor.x-other.x,actor.y-other.y)>=48,`${actor.id} collided with ${other.id}`);
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

test('agents walk back to their chair before sitting, without a straight-line desk transition', async () => {
  const scene=runtime(),actor=scene.AG.find(person=>person.id==='Tracer');
  assert.equal(await completeRoute(scene,scene.toSeat(actor)),true);
  assert.deepEqual([actor.x,actor.y],actor.seat);
  assert.equal(actor.mode,'sit');
});

test('a moving blocker causes the route to recalculate instead of leaving the agent stranded', async () => {
  const scene=runtime(),actor=scene.AG[0],blocker=scene.AG[4],token=scene.interruptMotion(actor);
  const target=scene.stationTarget(actor,'foos'),nodes=scene.wpath([actor.x,actor.y],target,actor),blockedPoint=nodes[1],route=scene.walkToPoint(actor,target,token);
  const blockerHome=[blocker.x,blocker.y];let finished=false,result,cleared=false;route.then(value=>{finished=true;result=value});
  scene.upd(.1);
  assert.ok(actor.tgt,'the route has started before the blocker appears');
  [blocker.x,blocker.y]=blockedPoint;blocker.mode='stand';
  for(let tick=0;tick<1200&&!finished;tick++){
    const blockedFor=actor.blockedFor||0;scene.upd(.05);
    if(!cleared&&blockedFor>1.15&&actor.tgt===null){[blocker.x,blocker.y]=blockerHome;cleared=true}
    await Promise.resolve();
  }
  assert.equal(cleared,true,'the route detects and yields to the temporary obstruction');
  assert.equal(result,true,'the route is recalculated after the obstruction clears');
  assert.ok(Math.hypot(actor.x-target[0],actor.y-target[1])<1);
});
