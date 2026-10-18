export const OFFICE_SIZE = Object.freeze({ width: 1264, height: 848 });

export const AGENT_PERSONAS = Object.freeze({
  Scout: Object.freeze({ tone: 'quick / alert', idleStyle: 'mobile field checks', tagline: 'Quick field checks', opening: 'Quick scan: checking the seed and its dataset context.', phrases: ['Seed checked.', 'Source noted.'] }),
  Tracer: Object.freeze({ tone: 'technical / focused', idleStyle: 'server and graph monitor', tagline: 'Directed paths, carefully mapped', opening: 'Mapping directed paths within the selected hop limit.', phrases: ['Paths are in scope.', 'Checking edge direction.'] }),
  Historian: Object.freeze({ tone: 'calm / contextual', idleStyle: 'archive and memory pods', tagline: 'Calm case-memory research', opening: 'Checking saved cases for shared transaction IDs.', phrases: ['Checking prior cases.', 'Overlap needs review.'] }),
  Analyst: Object.freeze({ tone: 'curious / interpretive', idleStyle: 'whiteboard and lounge', tagline: 'Curious, evidence-led patterns', opening: 'Reading verified evidence for patterns to review.', phrases: ['A pattern to check.', 'Interpretation stays separate.'] }),
  Skeptic: Object.freeze({ tone: 'precise / critical', idleStyle: 'evidence board review', tagline: 'Careful independent checks', opening: 'Checking paths and claims against graph evidence.', phrases: ['Verifying against source.', 'Unsupported claims stay out.'] }),
  Reporter: Object.freeze({ tone: 'composed / concise', idleStyle: 'report desk and presentation area', tagline: 'Clear findings, no embellishment', opening: 'Preparing a concise evidence-first report.', phrases: ['Report is organized.', 'Only qualified facts included.'] }),
});

// Stations are named waypoints in the office's walkability grid. The frontend
// pathfinder routes each trip around furniture; one idle agent moves at a time.
export const IDLE_ROUTINES = Object.freeze({
  Scout: Object.freeze({ home: 'arc', visits: ['arc2', 'shelf', 'copier'] }),
  Tracer: Object.freeze({ home: 'sB', visits: ['rack', 'board', 'mid'] }),
  Historian: Object.freeze({ home: 'shelf', visits: ['pods', 'arch', 'shelf', 'lounge'] }),
  Analyst: Object.freeze({ home: 'sA', visits: ['board', 'lounge', 'arc2'] }),
  Skeptic: Object.freeze({ home: 'sC', visits: ['mid', 'arch', 'shelf'] }),
  Reporter: Object.freeze({ home: 'printer', visits: ['bean', 'arch', 'printer'] }),
});

export const OFFICE_ZONES = Object.freeze({
  DESK_SCOUT: 'arc', DESK_TRACER: 'sB', DESK_ANALYST: 'sA', DESK_HISTORIAN: 'shelf',
  DESK_SKEPTIC: 'sC', DESK_REPORTER: 'printer', ARCHIVE: 'arch', SERVER_RACK: 'rack',
  MEETING_ZONE: 'mid', WHITEBOARD: 'board', LOUNGE: 'lounge', ARCADE: 'arc2', COFFEE: 'bean',
});

export const canTakeIdleBreak = ({ investigationState, agentState, moving = false, paused = false } = {}) =>
  investigationState !== 'running' && agentState === 'IDLE' && !moving && !paused;

export function nextIdleAgent(agentIds, agentStates, cursor = 0, unavailable = new Set()) {
  if (!agentIds.length) return null;
  for (let offset = 0; offset < agentIds.length; offset++) {
    const index = (cursor + offset) % agentIds.length;
    const id = agentIds[index];
    const agent = agentStates[id];
    if (IDLE_ROUTINES[id] && !unavailable.has(id) && canTakeIdleBreak({
      investigationState: agentStates.investigationState, agentState: agent?.state,
      moving: Boolean(agent?.moving), paused: Boolean(agentStates.paused),
    })) return { id, nextCursor: (index + 1) % agentIds.length };
  }
  return null;
}

export function nextIdleVisit(agent, visitCursor = 0) {
  const visits = IDLE_ROUTINES[agent]?.visits || [];
  if (!visits.length) return null;
  const index = visitCursor % visits.length;
  return { station: visits[index], nextCursor: (index + 1) % visits.length };
}

export const SPRITE_CLIP_LAYOUT = Object.freeze({
  walkF: Object.freeze({ frames: 8, frameWidth: 80, frameHeight: 136 }),
  walkB: Object.freeze({ frames: 8, frameWidth: 80, frameHeight: 136 }),
  idleF: Object.freeze({ frames: 4, frameWidth: 80, frameHeight: 136 }),
  idleB: Object.freeze({ frames: 4, frameWidth: 80, frameHeight: 136 }),
  talkF: Object.freeze({ frames: 6, frameWidth: 80, frameHeight: 136 }),
  sitB: Object.freeze({ frames: 4, frameWidth: 80, frameHeight: 90 }),
});

const ROLE_CLIP = Object.freeze({ Scout: 'scout', Tracer: 'tracer', Historian: 'historian', Analyst: 'profiler', Skeptic: 'skeptic', Reporter: 'reporter' });
const STATE_POSE = Object.freeze({
  STANDING: ['idleF', false], WALKING: ['walkF', false], SITTING: ['idleB', false],
  SLEEPING: ['idleB', false],
  STANDING_FRONT: ['idleF', false], STANDING_BACK: ['idleB', false],
  STANDING_LEFT: ['idleF', true], STANDING_RIGHT: ['idleF', false],
  WALK_FRONT: ['walkF', false], WALK_BACK: ['walkB', false],
  WALK_LEFT: ['walkF', true], WALK_RIGHT: ['walkF', false],
  // sitB is an authored torso-only desk overlay (80×90), not a full body.
  // Reuse complete, unstretched poses at chair feet anchors instead of inventing legs.
  SITTING_FRONT: ['idleF', false], SITTING_BACK: ['idleB', false],
  SITTING_LEFT: ['idleF', true], SITTING_RIGHT: ['idleF', false],
  WORKING: ['idleB', false], READING: ['idleB', false], THINKING: ['idleF', false],
  TALKING: ['talkF', false], LISTENING: ['idleF', false],
  RECEIVING_CONTEXT: ['idleF', true], SENDING_CONTEXT: ['talkF', false],
  MEETING: ['idleF', false], RELAXING: ['idleF', false],
  SLEEPING_OR_NAPPING: ['idleB', false], ERROR: ['idleF', false], SUCCESS: ['talkF', false],
});
export const REQUIRED_CHARACTER_STATES = Object.freeze(Object.keys(STATE_POSE));

export const CHAIR_FEET = Object.freeze({
  Analyst: Object.freeze([332, 516]), Tracer: Object.freeze([437, 568]),
  Skeptic: Object.freeze([672, 626]),
});

export const POSE_LIMITATIONS = 'The source has no complete bent-leg sitting, reading, or sleeping clips. These states reuse existing full-body poses; furniture provides chair occlusion.';

export const AGENT_LABEL_OFFSETS = Object.freeze({
  Scout: Object.freeze([-22, 0]), Tracer: Object.freeze([22, 0]),
  Historian: Object.freeze([-22, -13]), Analyst: Object.freeze([22, -13]),
  Skeptic: Object.freeze([-22, -26]), Reporter: Object.freeze([22, -26]),
});

export function officeLabelAnchor(agent, x, footY, scale = 1) {
  const [offsetX, offsetY] = AGENT_LABEL_OFFSETS[agent] || [0, 0];
  return { x: (x + offsetX) * scale, y: (footY - 140 + offsetY) * scale };
}

export const SPRITE_STATE_MAP = Object.freeze(Object.fromEntries(Object.keys(ROLE_CLIP).map(agent => [
  agent, Object.freeze(Object.fromEntries(Object.entries(STATE_POSE).map(([state, [pose, flipX]]) => [
    state, Object.freeze({ clip: `${ROLE_CLIP[agent]}_${pose}`, flipX, sourcePose: pose }),
  ]))),
])));

export const SPRITE_METADATA = Object.freeze(Object.fromEntries(Object.entries(SPRITE_CLIP_LAYOUT).map(([pose, frame]) => [pose, Object.freeze({
  ...frame, anchorX: 40, anchorY: frame.frameHeight,
  visualBounds: Object.freeze({ left: 0, top: 0, right: frame.frameWidth, bottom: frame.frameHeight }),
  feetPosition: Object.freeze({ x: frame.frameWidth / 2, y: frame.frameHeight }),
  interactionAnchor: Object.freeze({ x: frame.frameWidth / 2, y: Math.round(frame.frameHeight * 0.55) }),
  speechBubbleAnchor: Object.freeze({ x: frame.frameWidth / 2, y: 0 }),
})])));

export function validateSpriteCatalog(metadata = SPRITE_CLIP_LAYOUT) {
  const errors = [];
  for (const agent of Object.keys(ROLE_CLIP)) for (const state of REQUIRED_CHARACTER_STATES) {
    const mapping = SPRITE_STATE_MAP[agent][state];
    const pose = mapping.clip.slice(ROLE_CLIP[agent].length + 1);
    const frame = metadata[pose];
    if (!frame || !Number.isInteger(frame.frames) || frame.frames < 1 ||
        frame.frameWidth <= 0 || frame.frameHeight <= 0 ||
        mapping.flipX && !['idleF', 'walkF', 'sitB', 'talkF'].includes(pose)) errors.push(`${agent}.${state}`);
  }
  return { valid: errors.length === 0, errors };
}

export function spriteBounds(x, footY, width, height, scale = 1) {
  const w = width * scale, h = height * scale;
  return { left: x - w / 2, top: footY - h, right: x + w / 2, bottom: footY, width: w, height: h };
}

export function spriteBoundsFromMetadata(x, footY, metadata, scale = 1) {
  const b = metadata.visualBounds;
  const w = metadata.frameWidth * scale, h = metadata.frameHeight * scale;
  return { left: x - metadata.anchorX * scale + b.left * scale,
    top: footY - metadata.anchorY * scale + b.top * scale,
    right: x - metadata.anchorX * scale + b.right * scale,
    bottom: footY - metadata.anchorY * scale + b.bottom * scale,
    width: (b.right - b.left) * scale, height: (b.bottom - b.top) * scale };
}

export function spriteFitsOffice(bounds, office = OFFICE_SIZE) {
  return bounds.left >= 0 && bounds.top >= 0 && bounds.right <= office.width && bounds.bottom <= office.height;
}

export function furnitureOcclusionBounds(body, seated = false, scale = 1) {
  // The three authored chair backs start within 66 office pixels of the feet.
  // At a desk, distant divider masks must never repaint the head/shoulders.
  const top = seated ? Math.max(body.top, body.bottom - 66 * scale) : body.top - 8;
  return { left: body.left - 3, top, width: body.width + 6, height: body.bottom - top + 4 };
}

// Labels stay above their actor and clear of other labels and character bodies.
export function placeOfficeLabels(items, width, height) {
  const placed = [];
  const overlaps = (a, b) => a.left < b.right + 2 && a.right > b.left - 2 && a.top < b.bottom + 2 && a.bottom > b.top - 2;
  for (const item of items) {
    let chosen;
    search: for (const rise of [0, 12, 24, 40, 60, 90, 120]) for (const shift of [0, -24, 24, -48, 48, -72, 72]) {
      const left = Math.max(0, Math.min(width - item.width, item.x + shift - item.width / 2));
      const top = Math.max(0, Math.min(height - item.height, item.y - rise - item.height));
      const box = { left, top, right: left + item.width, bottom: top + item.height };
      if (!placed.some(other => overlaps(box, other)) && !items.some(other => other.id !== item.id && overlaps(box, other.body))) {
        chosen = box; break search;
      }
    }
    chosen ||= { left: Math.max(0, item.x - item.width / 2), top: Math.max(0, item.y - item.height),
      right: item.x + item.width / 2, bottom: item.y };
    placed.push({ id: item.id, ...chosen });
  }
  return placed;
}
