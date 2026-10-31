import * as THREE from 'three';
import { seeded } from './terrain';

interface Key { t: number; top: string; bottom: string; sun: string; sunI: number; hemiI: number; light: number; water: string; deep: string }

// time-of-day keyframes (t in [0,1): 0.25 dawn, 0.5 noon, 0.75 dusk, 0 midnight)
const KEYS: Key[] = [
  { t: 0.0, top: '#070b24', bottom: '#16214a', sun: '#8fa8ff', sunI: 0.35, hemiI: 0.42, light: 0.55, water: '#2b6c8f', deep: '#0b2147' },
  { t: 0.2, top: '#1d2a5a', bottom: '#8a5f7d', sun: '#ff9a6b', sunI: 0.35, hemiI: 0.45, light: 0.62, water: '#4b8fa6', deep: '#16365f' },
  { t: 0.28, top: '#5f86cc', bottom: '#ffc08a', sun: '#ffb87a', sunI: 0.95, hemiI: 0.62, light: 0.9, water: '#5fc4c2', deep: '#1f6296' },
  { t: 0.4, top: '#4a92e6', bottom: '#c4e6ff', sun: '#fff2d9', sunI: 1.5, hemiI: 0.8, light: 1.0, water: '#5fd1c7', deep: '#1c6fa8' },
  { t: 0.5, top: '#3d86e2', bottom: '#d3ecff', sun: '#fffbea', sunI: 1.7, hemiI: 0.85, light: 1.05, water: '#63d9cc', deep: '#1b72ae' },
  { t: 0.62, top: '#4a92e6', bottom: '#cbe7ff', sun: '#fff0cf', sunI: 1.5, hemiI: 0.8, light: 1.0, water: '#5fd1c7', deep: '#1c6fa8' },
  { t: 0.72, top: '#5a5cb0', bottom: '#ffa56e', sun: '#ff9650', sunI: 0.95, hemiI: 0.58, light: 0.82, water: '#5a9fb0', deep: '#2a4f8a' },
  { t: 0.8, top: '#222a63', bottom: '#6b4f84', sun: '#9a8cff', sunI: 0.45, hemiI: 0.36, light: 0.5, water: '#356f92', deep: '#122a55' },
  { t: 0.9, top: '#0a1030', bottom: '#1a2550', sun: '#8fa8ff', sunI: 0.35, hemiI: 0.42, light: 0.55, water: '#2b6c8f', deep: '#0b2147' },
  { t: 1.0, top: '#070b24', bottom: '#16214a', sun: '#8fa8ff', sunI: 0.35, hemiI: 0.42, light: 0.55, water: '#2b6c8f', deep: '#0b2147' },
];

const skyVert = /* glsl */ `
  varying vec3 vDir;
  void main() {
    vDir = normalize(position);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    gl_Position.z = gl_Position.w; // always at the far plane
  }
`;
const skyFrag = /* glsl */ `
  uniform vec3 uTop; uniform vec3 uBottom; uniform vec3 uSunDir; uniform vec3 uSunColor; uniform float uSunAmt;
  varying vec3 vDir;
  void main() {
    float y = vDir.y;
    vec3 col = mix(uBottom, uTop, pow(clamp(y, 0.0, 1.0), 0.55));
    col = mix(col, uBottom * 0.55, smoothstep(0.0, -0.35, y));
    float s = max(dot(normalize(vDir), uSunDir), 0.0);
    col += uSunColor * (pow(s, 600.0) * 2.0 + pow(s, 12.0) * 0.28) * uSunAmt;
    gl_FragColor = vec4(col, 1.0);
  }
`;

export class Sky {
  group = new THREE.Group();
  sun: THREE.DirectionalLight;
  hemi: THREE.HemisphereLight;
  sunDir = new THREE.Vector3(0, 1, 0);
  /** 0 at noon, 1 at night: used by lamps and stars */
  night = 0;
  light = 1;
  /** 0..1 storm intensity: greys and darkens the sky, flash adds lightning */
  storm = 0;
  flash = 0;
  fogColor = new THREE.Color();
  waterColor = new THREE.Color();
  deepColor = new THREE.Color();
  private mat: THREE.ShaderMaterial;
  private stars: THREE.Points;
  private moon: THREE.Mesh;

  constructor(private scene: THREE.Scene) {
    this.mat = new THREE.ShaderMaterial({
      vertexShader: skyVert,
      fragmentShader: skyFrag,
      side: THREE.BackSide,
      depthWrite: false,
      fog: false,
      uniforms: {
        uTop: { value: new THREE.Color() }, uBottom: { value: new THREE.Color() },
        uSunDir: { value: new THREE.Vector3(0, 1, 0) }, uSunColor: { value: new THREE.Color() }, uSunAmt: { value: 1 },
      },
    });
    const dome = new THREE.Mesh(new THREE.SphereGeometry(300, 32, 16), this.mat);
    dome.frustumCulled = false;
    dome.renderOrder = -10;
    this.group.add(dome);

    const rnd = seeded(7);
    const pts: number[] = [];
    for (let i = 0; i < 700; i++) {
      const u = rnd() * 2 - 1, a = rnd() * Math.PI * 2, r = Math.sqrt(1 - u * u);
      if (u < 0.02) continue;
      pts.push(Math.cos(a) * r * 280, u * 280, Math.sin(a) * r * 280);
    }
    const sg = new THREE.BufferGeometry();
    sg.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
    this.stars = new THREE.Points(sg, new THREE.PointsMaterial({ color: '#ffffff', size: 1.8, sizeAttenuation: false, transparent: true, depthWrite: false, fog: false }));
    this.group.add(this.stars);

    this.moon = new THREE.Mesh(new THREE.SphereGeometry(7, 20, 12), new THREE.MeshBasicMaterial({ color: '#f4f1e4', fog: false, transparent: true }));
    this.group.add(this.moon);

    this.sun = new THREE.DirectionalLight('#ffffff', 1.4);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(2048, 2048);
    const sc = this.sun.shadow.camera;
    sc.left = -34; sc.right = 34; sc.top = 34; sc.bottom = -34; sc.near = 1; sc.far = 160;
    this.sun.shadow.bias = -0.0006;
    this.sun.shadow.normalBias = 0.04;
    this.hemi = new THREE.HemisphereLight('#bfe3ff', '#b59a6a', 0.8);
    scene.add(this.group, this.sun, this.sun.target, this.hemi);
    scene.fog = new THREE.Fog('#bfe3ff', 70, 220);
    this.update(0.45, new THREE.Vector3());
  }

  private sample(t: number): { a: Key; b: Key; f: number } {
    for (let i = 0; i < KEYS.length - 1; i++)
      if (t >= KEYS[i].t && t <= KEYS[i + 1].t) return { a: KEYS[i], b: KEYS[i + 1], f: (t - KEYS[i].t) / (KEYS[i + 1].t - KEYS[i].t) };
    return { a: KEYS[0], b: KEYS[0], f: 0 };
  }

  update(tod: number, focus: THREE.Vector3) {
    const t = ((tod % 1) + 1) % 1;
    const { a, b, f } = this.sample(t);
    const mix = (x: string, y: string) => new THREE.Color(x).lerp(new THREE.Color(y), f);
    const top = mix(a.top, b.top), bottom = mix(a.bottom, b.bottom), sunC = mix(a.sun, b.sun);
    let sunI = a.sunI + (b.sunI - a.sunI) * f, hemiI = a.hemiI + (b.hemiI - a.hemiI) * f;
    this.light = a.light + (b.light - a.light) * f;
    if (this.storm > 0) {
      top.lerp(new THREE.Color('#38414d'), this.storm * 0.8);
      bottom.lerp(new THREE.Color('#58626f'), this.storm * 0.75);
      sunI *= 1 - 0.7 * this.storm;
      hemiI *= 1 - 0.2 * this.storm;
      this.light *= 1 - 0.32 * this.storm;
    }
    hemiI += this.flash * 2.2;
    this.waterColor.copy(mix(a.water, b.water));
    this.deepColor.copy(mix(a.deep, b.deep));

    const ang = (t - 0.25) * Math.PI * 2;
    this.sunDir.set(Math.cos(ang) * 0.9, Math.sin(ang), 0.35).normalize();
    const above = this.sunDir.y > -0.04;
    const lightDir = above ? this.sunDir : this.sunDir.clone().multiplyScalar(-1);
    this.sun.position.copy(focus).addScaledVector(lightDir, 70);
    this.sun.target.position.copy(focus);
    this.sun.color.copy(sunC);
    this.sun.intensity = sunI;
    this.hemi.intensity = hemiI;
    this.hemi.color.copy(top).lerp(new THREE.Color('#ffffff'), 0.35);
    this.hemi.groundColor.set('#8a7550').multiplyScalar(0.55 + this.light * 0.45);

    this.night = 1 - THREE.MathUtils.smoothstep(this.sunDir.y, -0.12, 0.28);
    const u = this.mat.uniforms;
    u.uTop.value.copy(top); u.uBottom.value.copy(bottom);
    u.uSunDir.value.copy(this.sunDir); u.uSunColor.value.copy(sunC);
    u.uSunAmt.value = 1 - this.night * 0.9;
    (this.stars.material as THREE.PointsMaterial).opacity = Math.pow(this.night, 1.5);
    this.moon.position.copy(this.sunDir).multiplyScalar(-230);
    (this.moon.material as THREE.MeshBasicMaterial).opacity = this.night;
    this.moon.visible = this.night > 0.02;
    this.fogColor.copy(bottom);
    (this.scene.fog as THREE.Fog).color.copy(bottom);
  }
}
