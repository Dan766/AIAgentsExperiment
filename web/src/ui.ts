import type { Frame, MessageRec, Replay } from './types';
import { Player } from './player';
import { WorldView } from './scene/worldview';

const ICON: Record<string, string> = { wood: '🪵', rope: '🪢', cloth: '🧵', food: '🍌', gold: '🪙' };
const PHASE_ICON: Record<string, string> = { dawn: '🌅', morning: '☀️', midday: '☀️', afternoon: '🌤️', dusk: '🌇', night: '🌙', ballot: '🗳️' };

const el = <T extends HTMLElement = HTMLElement>(html: string): T => {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstElementChild as T;
};
const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]!));

export class UI {
  private chat!: HTMLElement;
  private inspector!: HTMLElement;
  private raftEl!: HTMLElement;
  private clock!: HTMLElement;
  private slider!: HTMLInputElement;
  private playBtn!: HTMLButtonElement;
  private readout!: HTMLElement;
  private banner!: HTMLElement;
  private filter: 'all' | 'group' | 'dm' = 'all';
  private shown = 0;
  private lastPhaseKey = '';
  private colors = new Map<string, string>();

  constructor(private root: HTMLElement, private replay: Replay, private player: Player, private view: WorldView) {
    replay.personas.forEach((p) => this.colors.set(p.name, p.color));
    this.build();
    view.onSelect = () => this.renderInspector();
    window.addEventListener('keydown', (e) => this.key(e));
  }

  private build() {
    const r = this.replay;
    this.root.innerHTML = '';
    const top = el(`<header class="glass top">
      <div class="brand"><span class="logo">🏝️</span><div><b>Driftwood</b><small>${esc(r.run.label || `run ${r.run.id}`)} · seed ${r.run.seed}</small></div></div>
      <div class="clock"></div>
      <div class="raft"></div>
    </header>`);
    this.clock = top.querySelector('.clock')!;
    this.raftEl = top.querySelector('.raft')!;

    const left = el(`<aside class="glass chatp"><div class="ph"><b>Radio</b><div class="chips">
      <button data-f="all" class="on">All</button><button data-f="group">Group</button><button data-f="dm">Private 🔒</button></div></div>
      <div class="feed"></div></aside>`);
    this.chat = left.querySelector('.feed')!;
    left.querySelectorAll<HTMLButtonElement>('.chips button').forEach((b) =>
      b.addEventListener('click', () => {
        this.filter = b.dataset.f as any;
        left.querySelectorAll('.chips button').forEach((x) => x.classList.toggle('on', x === b));
        this.rebuildChat(this.shown);
      }));

    this.inspector = el(`<aside class="glass insp"></aside>`);

    const bar = el(`<footer class="glass tl">
      <button class="play" title="Play / pause (space)">▶</button>
      <button class="stepb" title="Next tick (→)">⏭</button>
      <div class="track"><input type="range" min="0" max="${this.player.last}" step="0.001" value="0"><div class="marks"></div></div>
      <div class="readout"></div>
      <div class="speeds"><button data-s="0.5">½×</button><button data-s="1" class="on">1×</button><button data-s="2">2×</button><button data-s="4">4×</button></div>
    </footer>`);
    this.playBtn = bar.querySelector('.play')!;
    this.slider = bar.querySelector('input')!;
    this.readout = bar.querySelector('.readout')!;
    this.playBtn.addEventListener('click', () => { this.player.toggle(); this.syncPlay(); });
    bar.querySelector('.stepb')!.addEventListener('click', () => { this.player.pause(); this.player.step(); this.syncPlay(); });
    this.slider.addEventListener('input', () => { this.player.pause(); this.player.seek(Math.round(+this.slider.value)); this.syncPlay(); });
    bar.querySelectorAll<HTMLButtonElement>('.speeds button').forEach((b) =>
      b.addEventListener('click', () => {
        this.player.speed = +b.dataset.s!;
        bar.querySelectorAll('.speeds button').forEach((x) => x.classList.toggle('on', x === b));
      }));
    this.buildMarks(bar.querySelector('.marks')!);

    this.banner = el(`<div class="banner" hidden></div>`);
    this.root.append(top, left, this.inspector, bar, this.banner);
  }

  private buildMarks(host: HTMLElement) {
    const n = this.player.last;
    this.replay.frames.forEach((f, i) => {
      const bad = f.events.some((e) => e.ok && (e.action === 'take' || e.action === 'tamper'));
      const vote = f.events.some((e) => e.action === 'vote');
      const newDay = i > 0 && f.phase === 'dawn';
      if (!bad && !vote && !newDay) return;
      const m = el(`<i class="${bad ? 'bad' : vote ? 'vote' : 'day'}" style="left:${(i / n) * 100}%" title="${bad ? 'sabotage' : vote ? 'ballot' : 'day ' + f.day}"></i>`);
      host.appendChild(m);
    });
  }

  private syncPlay() { this.playBtn.textContent = this.player.playing ? '⏸' : '▶'; }

  private key(e: KeyboardEvent) {
    if ((e.target as HTMLElement).tagName === 'INPUT' && (e.target as HTMLInputElement).type !== 'range') return;
    if (e.code === 'Space') { e.preventDefault(); this.player.toggle(); this.syncPlay(); }
    else if (e.code === 'ArrowRight') { this.player.pause(); this.player.step(); this.syncPlay(); }
    else if (e.code === 'ArrowLeft') { this.player.pause(); this.player.seek(this.player.idx - 1); this.syncPlay(); }
    else if (e.code === 'Escape') { this.view.select(null); this.view.follow = false; }
    else if (e.key === 'f' && this.view.selected) this.view.follow = !this.view.follow;
    else if (e.key === 'h') document.body.classList.toggle('hidepanels');
  }

  // ---- hooks from the player --------------------------------------------------------------
  onSeek(i: number) {
    this.shown = i;
    this.banner.hidden = true;
    this.lastPhaseKey = '';
    this.rebuildChat(i);
    this.renderAll(this.replay.frames[i]);
    this.slider.value = String(i);
    if (i === this.player.last) this.showEnd();
  }
  onSegmentStart(f: Frame, i: number) {
    this.shown = i;
    this.renderAll(f);
    this.banner.hidden = true;
  }
  onSegmentEnd(i: number) {
    if (i === this.player.last) { this.showEnd(); this.syncPlay(); }
  }
  onTime(to: number, p: number) { this.slider.value = String(to - 1 + p); }
  onMessage(m: MessageRec, f: Frame) { this.appendMessage(m, f, true); }

  // ---- rendering ------------------------------------------------------------------------
  private renderAll(f: Frame) {
    this.clock.innerHTML = `<span class="ph">${PHASE_ICON[f.phase] ?? ''}</span><b>Day ${f.day}</b><span>${f.phase}</span><small>tick ${f.tick}/${this.player.last}</small>`;
    this.readout.textContent = `${f.phase === 'ballot' ? 'ballot' : `d${f.day} ${f.phase}`}`;
    const rc = this.replay.scenario.recipe;
    const names: Record<string, string> = { hull: 'Hull', lashings: 'Lashings', sail: 'Sail', provisions: 'Food' };
    this.raftEl.innerHTML = Object.entries(rc).map(([k, v]) => {
      const p = Math.min(1, (f.raft[k] ?? 0) / v.need);
      return `<div class="rb" title="${names[k]} ${f.raft[k]}/${v.need}"><span>${ICON[v.resource] ?? ''} ${names[k]}</span><div><u style="width:${p * 100}%"></u></div><em>${f.raft[k]}/${v.need}</em></div>`;
    }).join('');
    this.renderInspector();
  }

  private latestThought(name: string): { tick: number; text: string; reflection?: string } | null {
    for (let i = this.shown; i >= 0; i--) {
      const f = this.replay.frames[i];
      const t = f.thoughts[name], rf = f.reflections[name];
      if (t || rf) {
        let reflection = rf;
        if (!reflection) for (let j = i; j >= Math.max(0, i - 8) && !reflection; j--) reflection = this.replay.frames[j].reflections[name];
        return { tick: f.tick - 1, text: t ?? '', reflection };
      }
    }
    return null;
  }

  private renderInspector() {
    const f = this.replay.frames[this.shown];
    const sel = this.view.selected;
    const list = this.replay.personas.map((p) => {
      const a = f.agents[p.name];
      return `<button class="chip ${p.name === sel ? 'on' : ''}" data-n="${p.name}"><i style="background:${p.color}"></i><span>${p.name}</span><u style="width:${a.energy}%"></u></button>`;
    }).join('');
    let detail = `<div class="hint">Click a character (or a name above) to inspect their inventory, private thoughts and who they trust. Press <kbd>F</kbd> to follow, <kbd>H</kbd> to hide panels.</div>`;
    if (sel) {
      const p = this.replay.personas.find((x) => x.name === sel)!;
      const a = f.agents[sel];
      const inv = Object.entries(a.inv).filter(([, n]) => n > 0).map(([k, n]) => `<span class="pill">${ICON[k] ?? ''} ${n}</span>`).join('') || '<span class="dim">empty-handed</span>';
      const caches = Object.entries(a.caches).flatMap(([loc, items]) => Object.entries(items).filter(([, n]) => n > 0).map(([k, n]) => `<span class="pill secret">🤫 ${loc}: ${ICON[k] ?? ''} ${n}</span>`)).join('');
      const th = this.latestThought(sel);
      const day = String(f.day);
      const b = this.replay.beliefs[day]?.[sel] ?? this.replay.beliefs[String(f.day - 1)]?.[sel];
      const trust = b ? Object.entries(b.trust).sort((x, y) => y[1] - x[1]).map(([n, v]) =>
        `<div class="tr"><span><i style="background:${this.colors.get(n)}"></i>${n}</span><div><u class="${v < 0 ? 'neg' : 'pos'}" style="width:${Math.abs(v) * 50}%;${v < 0 ? 'right:50%' : 'left:50%'}"></u></div><em>${v > 0 ? '+' : ''}${v.toFixed(1)}</em></div>`).join('') : '';
      const susp = b ? Object.entries(b.suspicions ?? {}).map(([n, t]) => `<li><b>${n}</b>: ${esc(t)}</li>`).join('') : '';
      detail = `<div class="who" style="--c:${p.color}"><div class="av" style="background:${p.color}"></div><div><b>${p.name}</b><small>${p.pronouns} · ${p.age} · ${a.loc.replace('_', ' ')}</small></div></div>
        <p class="bio">${esc(p.background)}</p>
        <div class="row"><span>Energy</span><div class="bar"><u style="width:${a.energy}%"></u></div><em>${a.energy}</em></div>
        <div class="row"><span>Carrying</span><div class="pills">${inv}${caches}</div></div>
        <h4>Private thought ${th ? `<small>tick ${th.tick}</small>` : ''}</h4>
        <blockquote>${th?.text ? esc(th.text) : '<span class="dim">…</span>'}</blockquote>
        ${th?.reflection ? `<h4>Last reflection</h4><blockquote class="refl">${esc(th.reflection)}</blockquote>` : ''}
        ${trust ? `<h4>Trust <small>from last night</small></h4><div class="trust">${trust}</div>` : ''}
        ${susp ? `<h4>Suspicions</h4><ul class="susp">${susp}</ul>` : ''}`;
    }
    this.inspector.innerHTML = `<div class="ph"><b>${sel ?? 'Survivors'}</b>${sel ? `<button class="x" title="Close">✕</button>` : ''}</div><div class="chips2">${list}</div><div class="detail">${detail}</div>`;
    this.inspector.querySelectorAll<HTMLButtonElement>('.chip').forEach((c) => c.addEventListener('click', () => this.view.focusOn(c.dataset.n!)));
    this.inspector.querySelector('.x')?.addEventListener('click', () => { this.view.select(null); this.view.follow = false; });
  }

  private rebuildChat(upto: number) {
    this.chat.innerHTML = '';
    this.lastPhaseKey = '';
    const msgs: [MessageRec, Frame][] = [];
    for (let i = Math.max(1, upto - 14); i <= upto; i++) this.replay.frames[i].messages.forEach((m) => msgs.push([m, this.replay.frames[i]]));
    msgs.forEach(([m, f]) => this.appendMessage(m, f, false));
    this.chat.scrollTop = this.chat.scrollHeight;
  }

  private appendMessage(m: MessageRec, f: Frame, scroll: boolean) {
    const dm = m.channel.startsWith('dm:');
    if ((this.filter === 'group' && dm) || (this.filter === 'dm' && !dm)) return;
    const key = `${f.day}-${f.phase}`;
    if (key !== this.lastPhaseKey) {
      this.lastPhaseKey = key;
      this.chat.appendChild(el(`<div class="div">${PHASE_ICON[f.phase] ?? ''} Day ${f.day} · ${f.phase}</div>`));
    }
    const c = this.colors.get(m.sender) ?? '#fff';
    this.chat.appendChild(el(`<div class="msg ${dm ? 'dm' : ''}"><i style="background:${c}"></i><div><b style="color:${c}">${m.sender}</b>${dm ? ` <span class="to">🔒 → ${m.channel.slice(3)}</span>` : ''}<p>${esc(m.text)}</p></div></div>`));
    if (scroll) this.chat.scrollTop = this.chat.scrollHeight;
  }

  private showEnd() {
    const rep = this.replay.report;
    if (!rep) return;
    const seats = (rep.seats ?? []).map((n: string) => `<span class="pill" style="border-color:${this.colors.get(n)}">${n}</span>`).join('');
    const bad = (rep.sabotage ?? []).filter((s: any) => s.ok);
    this.banner.innerHTML = `<h3>${rep.launched ? '⛵ The raft launched' : '🌀 The cyclone took them all'}</h3>
      ${rep.launched ? `<div class="pills">${seats}</div>` : ''}
      <p>${bad.length ? `${bad.length} acts of theft or tampering` : 'No theft or tampering'} · ${rep.cooperative_acts} gifts and deposits</p>
      <small>Scores: ${Object.entries(rep.agents).map(([n, a]: any) => `${n} ${a.score}`).join(' · ')}</small>`;
    this.banner.hidden = false;
  }
}
