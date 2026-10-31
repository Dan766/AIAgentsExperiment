import './style.css';
import type { Replay } from './types';
import { Player } from './player';
import { WorldView } from './scene/worldview';
import { UI } from './ui';

async function main() {
  const app = document.getElementById('app')!;
  const stage = document.createElement('div');
  stage.className = 'stage';
  const hud = document.createElement('div');
  hud.className = 'hud';
  app.append(stage, hud);

  const file = new URLSearchParams(location.search).get('run') ?? 'sample-run.json';
  const res = await fetch(import.meta.env.BASE_URL + file);
  if (!res.ok) {
    hud.innerHTML = `<div class="banner">Could not load <code>${file}</code>. Export one with <code>driftwood export</code>.</div>`;
    return;
  }
  const replay: Replay = await res.json();

  const view = new WorldView(stage, replay);
  let ui: UI;
  const player = new Player(view, replay, {
    onSeek: (i) => ui.onSeek(i),
    onSegmentStart: (f, i) => ui.onSegmentStart(f, i),
    onSegmentEnd: (i) => ui.onSegmentEnd(i),
    onMessage: (m, f) => ui.onMessage(m, f),
    onTime: (to, p) => ui.onTime(to, p),
  });
  ui = new UI(hud, replay, player, view);
  view.start();
  player.seek(0);
  (window as any).driftwood = { view, player, replay };
}

main();
