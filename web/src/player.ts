import type { EventRec, Frame, MessageRec, Replay } from './types';
import { Character, slotPosition } from './scene/characters';
import { WorldView } from './scene/worldview';

const PHASE_T: Record<string, number> = { dawn: 0.25, morning: 0.33, midday: 0.5, afternoon: 0.62, dusk: 0.75, night: 0.9 };

/** Monotonic game time in days: day 1 dawn = 0.25. The ballot comes right after the last night. */
export function gameTime(f: Frame): number {
  if (f.phase === 'ballot') return f.day - 1 + 1.25;
  return f.day - 1 + (PHASE_T[f.phase] ?? 0.5);
}

export interface PlayerHooks {
  onSeek(idx: number): void;
  onSegmentStart(frame: Frame, idx: number): void;
  onSegmentEnd(idx: number): void;
  onMessage(m: MessageRec, frame: Frame): void;
  onTime(idx: number, progress: number): void;
}

const ITEM_ICON: Record<string, string> = { wood: '🪵', rope: '🪢', cloth: '🧵', food: '🍌', gold: '🪙' };

export class Player {
  idx = 0;
  playing = false;
  speed = 1;
  baseTickSeconds = 4.6;
  private seg: { from: number; to: number; t0: number; dur: number } | null = null;
  private scheduled: { at: number; fn: () => void }[] = [];
  private lastTime = 0;

  constructor(private view: WorldView, public replay: Replay, private hooks: PlayerHooks) {
    view.onFrame((_dt, time) => this.update(time));
  }

  get last() { return this.replay.frames.length - 1; }
  get frame() { return this.replay.frames[this.idx]; }

  private slots(frame: Frame): Map<string, { x: number; z: number }> {
    const byLoc = new Map<string, string[]>();
    for (const p of this.replay.personas) {
      const loc = frame.agents[p.name].loc;
      byLoc.set(loc, [...(byLoc.get(loc) ?? []), p.name]);
    }
    const out = new Map<string, { x: number; z: number }>();
    for (const [loc, names] of byLoc) names.forEach((n, i) => out.set(n, slotPosition(loc, i, names.length)));
    return out;
  }

  seek(i: number) {
    i = Math.max(0, Math.min(this.last, i));
    this.seg = null;
    this.scheduled = [];
    this.idx = i;
    const f = this.replay.frames[i];
    const slots = this.slots(f);
    for (const [name, c] of this.view.characters) {
      const s = slots.get(name)!;
      c.placeAt(s.x, s.z);
      c.setEnergy(f.agents[name].energy);
      c.clearBubbles();
    }
    this.view.raft.setProgress(f.raft, true);
    this.view.setStockpile(f.stockpile);
    this.view.setTod(gameTime(f) % 1);
    this.hooks.onSeek(i);
  }

  play() { this.playing = true; }
  pause() { this.playing = false; }
  toggle() { this.playing ? this.pause() : this.play(); if (this.playing && this.idx >= this.last && !this.seg) this.seek(0); }

  /** Jump to the next frame with an animated transition. */
  step() {
    if (this.seg) this.finish();
    if (this.idx < this.last) this.start(this.idx + 1);
  }

  private at(t0: number, dur: number, frac: number, fn: () => void) {
    this.scheduled.push({ at: t0 + dur * frac, fn });
  }

  private start(to: number) {
    const from = this.replay.frames[to - 1], f = this.replay.frames[to];
    const dur = this.baseTickSeconds / this.speed;
    const t0 = this.view.time;
    this.seg = { from: to - 1, to, t0, dur };
    const slots = this.slots(f);
    const jitter = (n: string) => ((n.charCodeAt(0) * 7 + n.length * 13) % 10) / 10;

    for (const [name, c] of this.view.characters) {
      const s = slots.get(name)!;
      const before = from.agents[name].loc, after = f.agents[name].loc;
      if (before !== after) c.walkTo(s.x, s.z, t0 + dur * (0.03 + jitter(name) * 0.1), dur * 0.62);
      else {
        // slots shift when others come and go: ease into the new spot
        const p = c.position;
        if (Math.hypot(p.x - s.x, p.z - s.z) > 0.1) c.walkTo(s.x, s.z, t0 + dur * 0.55, dur * 0.35);
      }
      this.at(t0, dur, 0.5, () => c.setEnergy(f.agents[name].energy));
    }

    f.events.forEach((ev) => this.animateEvent(ev, t0, dur, jitter(ev.actor)));
    this.at(t0, dur, 0.55, () => { this.view.raft.setProgress(f.raft); this.view.setStockpile(f.stockpile); });

    f.messages.forEach((m, i) => {
      const frac = 0.08 + (i / Math.max(1, f.messages.length)) * 0.8;
      this.at(t0, dur, frac, () => {
        this.view.characters.get(m.sender)?.say(m.text, m.channel, Math.min(9000, Math.max(4200, dur * 1500)));
        this.hooks.onMessage(m, f);
      });
    });
    this.hooks.onSegmentStart(f, to);
  }

  private animateEvent(ev: EventRec, t0: number, dur: number, j: number) {
    const actor = this.view.characters.get(ev.actor);
    if (!actor) return;
    const start = t0 + dur * (0.14 + j * 0.16);
    const len = dur * 0.5;
    const float = (c: Character, text: string, cls = '', frac = 0.42) => this.at(t0, dur, frac + j * 0.12, () => c.floatText(text, cls));
    if (!ev.ok) {
      if (ev.action !== 'move') float(actor, '✗', 'dim', 0.3);
      return;
    }
    const d = ev.data;
    switch (ev.action) {
      case 'gather':
        actor.act(d.resource === 'wood' ? 'chop' : 'reach', start, len);
        float(actor, `+${d.n} ${ITEM_ICON[d.resource] ?? d.resource}`);
        break;
      case 'search_wreck': {
        actor.act('reach', start, len);
        const got = Object.entries(d).filter(([, n]) => (n as number) > 0).map(([k, n]) => `+${n} ${ITEM_ICON[k] ?? k}`).join(' ');
        float(actor, got || 'nothing', got.includes('🪙') ? 'gold' : 'dim');
        break;
      }
      case 'build': actor.act('hammer', start, len); float(actor, `+${d.n} ${d.component}`, 'good'); break;
      case 'tamper': actor.act('hammer', start, len * 0.8); float(actor, `💥 −${d.lost} ${d.component}`, 'bad'); break;
      case 'deposit': case 'withdraw': actor.act('hop', start, len * 0.6); float(actor, `${d.n} ${ITEM_ICON[d.item] ?? d.item} ${ev.action === 'deposit' ? '→ pile' : '← pile'}`); break;
      case 'give': {
        actor.act('give', start, len * 0.7);
        const tgt = this.view.characters.get(d.to);
        if (tgt) float(tgt, `+${d.n} ${ITEM_ICON[d.item] ?? d.item}`, 'good', 0.55);
        break;
      }
      case 'take': {
        const victim = this.view.characters.get(d.from);
        actor.act('lunge', start, len * 0.7, victim?.position);
        victim?.act('flinch', start + len * 0.25, len * 0.5);
        float(actor, `+${d.n} ${ITEM_ICON[d.item] ?? d.item}`, 'steal', 0.5);
        if (victim) float(victim, `−${d.n} ${ITEM_ICON[d.item] ?? d.item}`, 'bad', 0.5);
        break;
      }
      case 'stash': case 'unstash': actor.act('sit', start, len * 0.7); float(actor, ev.action === 'stash' ? '🤫 hid it' : 'retrieved', 'dim'); break;
      case 'eat': case 'rest': actor.act('sit', start, len); break;
      case 'vote': actor.act('hop', start, len * 0.5); float(actor, '🗳️', ''); break;
    }
  }

  private finish() {
    if (!this.seg) return;
    const run = this.scheduled.splice(0);
    run.forEach((s) => s.fn());
    const to = this.seg.to;
    this.seg = null;
    this.idx = to;
    this.view.setTod(gameTime(this.replay.frames[to]) % 1);
    this.hooks.onSegmentEnd(to);
  }

  private update(time: number) {
    this.lastTime = time;
    if (this.scheduled.length) {
      const due = this.scheduled.filter((s) => s.at <= time);
      if (due.length) {
        this.scheduled = this.scheduled.filter((s) => s.at > time);
        due.forEach((s) => s.fn());
      }
    }
    if (this.seg) {
      const p = (time - this.seg.t0) / this.seg.dur;
      const a = gameTime(this.replay.frames[this.seg.from]), b = gameTime(this.replay.frames[this.seg.to]);
      const e = Math.min(1, Math.max(0, p));
      this.view.setTod((a + (b - a) * (e * e * (3 - 2 * e))) % 1);
      this.hooks.onTime(this.seg.to, e);
      if (p >= 1) this.finish();
    } else if (this.playing && this.idx < this.last) {
      this.start(this.idx + 1);
    } else if (this.playing && this.idx >= this.last) {
      this.playing = false;
    }
  }
}
