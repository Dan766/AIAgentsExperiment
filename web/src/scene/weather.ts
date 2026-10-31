import * as THREE from 'three';

/** Rain streaks that follow the camera target. `level` (0..1) also drives sky darkness and wave height. */
export class Weather {
  level = 0;
  flash = 0;
  private target = 0;
  private hold = 0;
  private lines: THREE.LineSegments;
  private pos: Float32Array;
  private drops: Float32Array; // x, y, z per drop
  private readonly N = 1500;
  private nextBolt = 0;

  constructor(scene: THREE.Scene) {
    this.pos = new Float32Array(this.N * 6);
    this.drops = new Float32Array(this.N * 3);
    for (let i = 0; i < this.N; i++) {
      this.drops[i * 3] = (Math.random() - 0.5) * 60;
      this.drops[i * 3 + 1] = Math.random() * 32;
      this.drops[i * 3 + 2] = (Math.random() - 0.5) * 60;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(this.pos, 3));
    this.lines = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color: '#cfdcff', transparent: true, opacity: 0, depthWrite: false, fog: false }));
    this.lines.frustumCulled = false;
    this.lines.visible = false;
    scene.add(this.lines);
  }

  /** Start a storm that lasts roughly `seconds`, then fades out. */
  storm(seconds: number) {
    this.target = 1;
    this.hold = seconds;
  }

  clear() {
    this.target = 0; this.hold = 0; this.level = 0; this.flash = 0;
  }

  update(dt: number, center: THREE.Vector3) {
    this.hold -= dt;
    if (this.hold <= 0) this.target = 0;
    this.level += (this.target - this.level) * Math.min(1, dt * 1.6);
    if (this.level < 0.004) this.level = 0;
    this.flash = Math.max(0, this.flash - dt * 3.5);
    if (this.level > 0.6) {
      this.nextBolt -= dt;
      if (this.nextBolt <= 0) { this.flash = 1; this.nextBolt = 2.5 + Math.random() * 4; }
    }
    const visible = this.level > 0.02;
    this.lines.visible = visible;
    if (!visible) return;
    (this.lines.material as THREE.LineBasicMaterial).opacity = this.level * 0.5;
    const speed = 30;
    for (let i = 0; i < this.N; i++) {
      let y = this.drops[i * 3 + 1] - speed * dt;
      if (y < 0) y += 32;
      this.drops[i * 3 + 1] = y;
      const x = center.x + this.drops[i * 3], z = center.z + this.drops[i * 3 + 2];
      const o = i * 6;
      this.pos[o] = x; this.pos[o + 1] = y; this.pos[o + 2] = z;
      this.pos[o + 3] = x - 0.3; this.pos[o + 4] = y - 1.2; this.pos[o + 5] = z;
    }
    (this.lines.geometry.attributes.position as THREE.BufferAttribute).needsUpdate = true;
  }
}
