import * as THREE from 'three';

const std = (color: string, extra: Partial<THREE.MeshStandardMaterialParameters> = {}) =>
  new THREE.MeshStandardMaterial({ color, flatShading: true, roughness: 0.9, ...extra });

const LOGS = 8;

/** The raft: grows log by log as progress comes in, and shudders red when someone tears it apart. */
export class Raft {
  group = new THREE.Group();
  private logs: THREE.Mesh[] = [];
  private bands: THREE.Mesh[] = [];
  private beams: THREE.Mesh[] = [];
  private mast: THREE.Mesh;
  private sail: THREE.Mesh;
  private crates: THREE.Mesh[] = [];
  private logMat = std('#9b6a3a');
  private flash = 0;
  private shake = 0;
  private shown = { hull: 0, lashings: 0, sail: 0, provisions: 0 };
  private target = { hull: 0, lashings: 0, sail: 0, provisions: 0 };
  private need: Record<string, number>;

  constructor(need: Record<string, number>) {
    this.need = need;
    for (let i = 0; i < LOGS; i++) {
      const log = new THREE.Mesh(new THREE.CylinderGeometry(0.23, 0.23, 4.2, 7), this.logMat.clone());
      log.rotation.x = Math.PI / 2;
      log.position.set((i - (LOGS - 1) / 2) * 0.44, 0.28, 0);
      log.castShadow = log.receiveShadow = true;
      log.visible = false;
      this.logs.push(log);
      this.group.add(log);
    }
    const bandM = std('#4a3523');
    for (let i = 0; i < 4; i++) {
      const band = new THREE.Mesh(new THREE.BoxGeometry(LOGS * 0.44 + 0.1, 0.1, 0.13), bandM);
      band.position.set(0, 0.54, -1.5 + i * 1.0);
      band.castShadow = true;
      band.visible = false;
      this.bands.push(band);
      this.group.add(band);
    }
    for (const z of [-0.9, 0.9]) {
      const beam = new THREE.Mesh(new THREE.BoxGeometry(LOGS * 0.44 + 0.3, 0.14, 0.22), std('#7b5430'));
      beam.position.set(0, 0.65, z);
      beam.castShadow = true;
      beam.visible = false;
      this.beams.push(beam);
      this.group.add(beam);
    }
    this.mast = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.1, 3.6, 6), std('#6b4a2a'));
    this.mast.geometry.translate(0, 1.8, 0);
    this.mast.position.set(0, 0.7, -0.2);
    this.mast.castShadow = true;
    this.mast.visible = false;
    this.group.add(this.mast);
    this.sail = new THREE.Mesh(new THREE.PlaneGeometry(2.4, 2.6, 6, 6), std('#efe4c8', { side: THREE.DoubleSide, flatShading: true }));
    this.sail.geometry.translate(0, 1.3, 0);
    this.sail.position.set(0, 1.55, -0.2);
    this.sail.castShadow = true;
    this.sail.visible = false;
    this.group.add(this.sail);
    const crateM = std('#b5834a');
    for (let i = 0; i < 8; i++) {
      const c = new THREE.Mesh(new THREE.BoxGeometry(0.42, 0.34, 0.42), crateM);
      c.position.set(-1.2 + (i % 4) * 0.55 + (i > 3 ? 0.12 : 0), 0.85 + (i > 3 ? 0.34 : 0), 1.2 - (i > 3 ? 0.1 : 0));
      c.castShadow = true;
      c.visible = false;
      this.crates.push(c);
      this.group.add(c);
    }
  }

  /** Set progress; shrinking progress means sabotage, so react. */
  setProgress(p: Record<string, number>, instant = false) {
    const damaged = ['hull', 'lashings', 'sail', 'provisions'].some((k) => (p[k] ?? 0) < (this.target as any)[k]);
    for (const k of Object.keys(this.target)) (this.target as any)[k] = p[k] ?? 0;
    if (damaged && !instant) {
      this.flash = 1;
      this.shake = 1;
    }
    if (instant) this.shown = { ...this.target };
  }

  complete(): boolean {
    return Object.entries(this.need).every(([k, n]) => (this.target as any)[k] >= n);
  }

  update(dt: number, time: number) {
    for (const k of Object.keys(this.shown) as (keyof typeof this.shown)[]) {
      const d = this.target[k] - this.shown[k];
      this.shown[k] += Math.abs(d) < 0.02 ? d : d * Math.min(1, dt * 3);
    }
    const f = (k: keyof typeof this.shown) => Math.max(0, Math.min(1, this.shown[k] / (this.need[k] || 1)));
    const nLogs = f('hull') * LOGS;
    this.logs.forEach((l, i) => {
      const s = Math.max(0, Math.min(1, nLogs - i));
      l.visible = s > 0.01;
      l.scale.set(s, 1, s);
    });
    const lash = f('lashings');
    this.bands.forEach((b, i) => {
      const s = Math.max(0, Math.min(1, lash * 4 - i));
      b.visible = s > 0.02 && nLogs > 1;
      b.scale.x = Math.max(0.05, s);
    });
    this.beams.forEach((b, i) => (b.visible = lash > 0.45 + i * 0.2 && nLogs > 2));
    const sl = f('sail');
    this.mast.visible = sl > 0.01;
    this.mast.scale.y = Math.min(1, 0.3 + sl * 0.9);
    this.sail.visible = sl > 0.12;
    this.sail.scale.set(Math.min(1, sl * 1.2 + 0.1), sl, 1);
    this.sail.position.y = 1.55 * (0.4 + 0.6 * sl);
    const wave = Math.sin(time * 1.4) * 0.05;
    this.sail.rotation.y = Math.sin(time * 0.8) * 0.08; // gentle billow
    const nProv = Math.round(f('provisions') * 8);
    this.crates.forEach((c, i) => (c.visible = i < nProv));

    this.flash = Math.max(0, this.flash - dt * 1.4);
    this.shake = Math.max(0, this.shake - dt * 1.6);
    for (const l of this.logs) {
      const m = l.material as THREE.MeshStandardMaterial;
      m.emissive.setRGB(this.flash * 0.9, this.flash * 0.1, 0);
    }
    this.group.position.y = wave * 0.2;
    this.group.rotation.z = Math.sin(time * 30) * 0.02 * this.shake;
    this.group.rotation.x = Math.cos(time * 27) * 0.02 * this.shake;
  }
}
