import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js';
import type { Replay } from '../types';
import { Character } from './characters';
import { campfire, crate, dock, lookout, scatterIsland, tent, wreck } from './props';
import { Raft } from './raft';
import { Sky } from './sky';
import { ANCHORS, buildTerrain, heightAt } from './terrain';
import { Water } from './water';

const BUILD_RAFT_OFFSET = { x: 2.6, z: 0.9 };

export class WorldView {
  renderer: THREE.WebGLRenderer;
  labels: CSS2DRenderer;
  scene = new THREE.Scene();
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  sky: Sky;
  water: Water;
  raft: Raft;
  characters = new Map<string, Character>();
  selected: string | null = null;
  follow = false;
  onSelect: (name: string | null) => void = () => {};
  time = 0;
  private hooks: ((dt: number, time: number) => void)[] = [];
  private fire!: ReturnType<typeof campfire>;
  private palms: THREE.Group[] = [];
  private flag?: THREE.Object3D;
  private crates: THREE.Mesh[] = [];
  private raycaster = new THREE.Raycaster();
  private last = performance.now();
  private focus = new THREE.Vector3(2, 0, 3);

  constructor(private container: HTMLElement, replay: Replay) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    container.appendChild(this.renderer.domElement);

    this.labels = new CSS2DRenderer();
    this.labels.domElement.className = 'labels';
    container.appendChild(this.labels.domElement);

    this.camera = new THREE.PerspectiveCamera(42, 1, 0.5, 700);
    this.camera.position.set(-10, 31, 52);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.copy(this.focus);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.07;
    this.controls.maxPolarAngle = Math.PI * 0.485;
    this.controls.minDistance = 7;
    this.controls.maxDistance = 95;

    this.sky = new Sky(this.scene);
    this.water = new Water();
    this.scene.add(this.water.mesh);
    this.scene.add(buildTerrain());
    this.buildProps(replay);

    const need = Object.fromEntries(Object.entries(replay.scenario.recipe).map(([k, v]) => [k, v.need]));
    this.raft = new Raft(need);
    const rx = ANCHORS.build_site.x + BUILD_RAFT_OFFSET.x, rz = ANCHORS.build_site.z + BUILD_RAFT_OFFSET.z;
    this.raft.group.position.set(rx, Math.max(heightAt(rx, rz), 0.1) + 0.12, rz);
    this.raft.group.rotation.y = -0.55;
    this.scene.add(this.raft.group);

    replay.personas.forEach((p, i) => {
      const c = new Character(p, i);
      this.characters.set(p.name, c);
      this.scene.add(c.group);
    });

    this.renderer.domElement.addEventListener('pointerdown', (e) => this.pointerDown(e));
    this.renderer.domElement.addEventListener('pointerup', (e) => this.pointerUp(e));
    new ResizeObserver(() => this.resize()).observe(container);
    this.resize();
  }

  private buildProps(replay: Replay) {
    const { group, palms } = scatterIsland();
    this.palms = palms;
    this.scene.add(group);

    this.fire = campfire();
    const fx = ANCHORS.camp.x - 1.6, fz = ANCHORS.camp.z - 2.1;
    this.fire.group.position.set(fx, heightAt(fx, fz), fz);
    this.scene.add(this.fire.group);

    const colors = ['#d9754a', '#5a8fd0', '#c9a23e'];
    [[-4.4, 11.3], [4.2, 11.6], [-7.2, 12.2]].forEach(([x, z], i) => {
      const t = tent(colors[i]);
      t.position.set(x, heightAt(x, z), z);
      t.rotation.y = i * 0.9 + 0.4;
      this.scene.add(t);
    });

    const lk = lookout();
    const lx = ANCHORS.lookout.x + 1.8, lz = ANCHORS.lookout.z - 1.2;
    lk.position.set(lx, heightAt(lx, lz), lz);
    this.scene.add(lk);
    this.flag = lk.userData.flag;

    const dk = dock();
    const a = ANCHORS.lagoon;
    dk.position.set(a.x - 0.4, 0.14, a.z - 0.2);
    dk.rotation.y = -Math.atan2(1.5 - a.z, -11.5 - a.x);
    this.scene.add(dk);

    const w = wreck();
    w.position.set(ANCHORS.wreck.x + 2.4, 0.0, ANCHORS.wreck.z - 1.9);
    this.scene.add(w);

    // build site: sand-marking stakes
    const stakeM = new THREE.MeshStandardMaterial({ color: '#8a5f35', flatShading: true });
    for (let i = 0; i < 6; i++) {
      const s = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.8, 5), stakeM);
      const ang = (i / 6) * Math.PI * 2;
      const sx = ANCHORS.build_site.x + BUILD_RAFT_OFFSET.x + Math.cos(ang) * 3.1, sz = ANCHORS.build_site.z + BUILD_RAFT_OFFSET.z + Math.sin(ang) * 2.4;
      s.position.set(sx, heightAt(sx, sz) + 0.3, sz);
      s.castShadow = true;
      this.scene.add(s);
    }
    void replay;
  }

  setStockpile(stock: Record<string, number>) {
    const total = Object.values(stock).reduce((a, b) => a + b, 0);
    const want = Math.min(10, Math.ceil(total / 2.5));
    const bx = ANCHORS.camp.x + 2.6, bz = ANCHORS.camp.z - 2.0;
    while (this.crates.length < want) {
      const i = this.crates.length;
      const c = crate(i % 3 === 0 ? '#b58a4f' : '#a8793f');
      const col = i % 4, row = Math.floor(i / 4), layer = Math.floor(i / 8);
      const x = bx + col * 0.7 - row * 0.2, z = bz + (row % 2) * 0.7;
      c.position.set(x, heightAt(x, z) + 0.25 + layer * 0.5, z);
      c.rotation.y = (i * 0.37) % 0.4;
      this.scene.add(c);
      this.crates.push(c);
    }
    this.crates.forEach((c, i) => (c.visible = i < want));
  }

  select(name: string | null) {
    if (this.selected) this.characters.get(this.selected)?.setSelected(false);
    this.selected = name;
    if (name) this.characters.get(name)?.setSelected(true);
    this.onSelect(name);
  }

  focusOn(name: string) {
    const c = this.characters.get(name);
    if (!c) return;
    this.select(name);
    this.follow = true;
  }

  private downAt = { x: 0, y: 0 };
  private pointerDown(e: PointerEvent) { this.downAt = { x: e.clientX, y: e.clientY }; }
  private pointerUp(e: PointerEvent) {
    if (Math.hypot(e.clientX - this.downAt.x, e.clientY - this.downAt.y) > 5) return;
    const r = this.renderer.domElement.getBoundingClientRect();
    this.raycaster.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), this.camera);
    const hits = this.raycaster.intersectObjects([...this.characters.values()].map((c) => c.group), true);
    for (const h of hits) {
      let o: THREE.Object3D | null = h.object;
      while (o && !o.userData.character) o = o.parent;
      if (o) { this.select((o.userData.character as Character).name); return; }
    }
    this.select(null);
    this.follow = false;
  }

  resize() {
    const w = this.container.clientWidth, h = this.container.clientHeight;
    this.renderer.setSize(w, h);
    this.labels.setSize(w, h);
    this.camera.aspect = w / Math.max(h, 1);
    this.camera.updateProjectionMatrix();
  }

  onFrame(fn: (dt: number, time: number) => void) { this.hooks.push(fn); }

  setTod(tod: number) {
    this.sky.update(tod, this.focus);
    const u = this.water.mat.uniforms;
    u.uShallow.value.copy(this.sky.waterColor);
    u.uDeep.value.copy(this.sky.deepColor);
    u.uSunDir.value.copy(this.sky.sunDir);
    u.uSunColor.value.copy(this.sky.sun.color);
    u.uLight.value = this.sky.light;
    u.uFog.value.copy(this.sky.fogColor);
  }

  start() {
    const loop = () => {
      requestAnimationFrame(loop);
      const now = performance.now();
      const dt = Math.min(0.05, (now - this.last) / 1000);
      this.last = now;
      this.time += dt;
      const t = this.time;
      this.water.update(t);
      for (const h of this.hooks) h(dt, t);
      this.raft.update(dt, t);
      for (const c of this.characters.values()) c.update(t, dt);
      this.palms.forEach((p, i) => { const cr = p.userData.crown as THREE.Object3D; cr.rotation.z = Math.sin(t * 1.1 + i) * 0.03; cr.rotation.x = Math.cos(t * 0.9 + i * 1.7) * 0.03; });
      const flick = 0.85 + Math.sin(t * 17) * 0.08 + Math.sin(t * 31) * 0.07;
      this.fire.light.intensity = (3 + this.sky.night * 22) * flick;
      this.fire.flames.forEach((f, i) => { f.scale.set(1 + Math.sin(t * 13 + i) * 0.12, flick + Math.sin(t * 9 + i * 2) * 0.15, 1 + Math.cos(t * 11 + i) * 0.12); f.rotation.y = t * (2 + i); });
      if (this.flag) this.flag.rotation.y = Math.sin(t * 2.2) * 0.35;

      if (this.follow && this.selected) {
        const c = this.characters.get(this.selected)!;
        const p = c.group.position;
        const prev = this.controls.target.clone();
        this.controls.target.lerp(new THREE.Vector3(p.x, p.y + 1, p.z), Math.min(1, dt * 3));
        this.camera.position.add(this.controls.target.clone().sub(prev));
      }
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
      this.labels.render(this.scene, this.camera);
    };
    loop();
  }
}
