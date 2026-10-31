import * as THREE from 'three';
import { CSS2DObject } from 'three/examples/jsm/renderers/CSS2DRenderer.js';
import type { Persona } from '../types';
import { ANCHORS, walkHeight } from './terrain';

const SKIN = ['#f0c8a0', '#c68d63', '#e8b48c', '#f3d2b3', '#9a6a46', '#e9bf96', '#7d5438', '#d9a67a'];
const HAIR = ['#8a8a8a', '#3a2a1e', '#1a1a1e', '#3b2f6b', '#2a1d17', '#4a3a2a', '#1c1c20', '#6b4f2a'];

const std = (color: string, extra: Partial<THREE.MeshStandardMaterialParameters> = {}) =>
  new THREE.MeshStandardMaterial({ color, roughness: 0.8, flatShading: true, ...extra });

function part<T extends THREE.BufferGeometry>(geo: T, m: THREE.Material, shadow = true) {
  const o = new THREE.Mesh(geo, m);
  o.castShadow = shadow;
  return o;
}

export type ActKind = 'chop' | 'reach' | 'hammer' | 'lunge' | 'flinch' | 'give' | 'hop' | 'sit' | 'wave';

export function slotPosition(loc: string, index: number, count: number): { x: number; z: number } {
  const a = ANCHORS[loc] ?? ANCHORS.camp;
  if (count <= 1) return { x: a.x, z: a.z };
  const r = Math.min(0.85 + count * 0.16, 2.3);
  const ang = (index / count) * Math.PI * 2 + 0.6;
  return { x: a.x + Math.cos(ang) * r, z: a.z + Math.sin(ang) * r };
}

function accessory(kind: string, head: THREE.Group, body: THREE.Group, color: string) {
  const dark = std('#222532');
  switch (kind) {
    case 'bandana': {
      const band = part(new THREE.TorusGeometry(0.3, 0.06, 6, 14), std('#d9462f'));
      band.rotation.x = Math.PI / 2; band.position.y = 0.12; head.add(band);
      const knot = part(new THREE.SphereGeometry(0.09, 6, 5), std('#d9462f'));
      knot.position.set(0, 0.1, -0.33); head.add(knot);
      break;
    }
    case 'sunglasses': {
      const bar = part(new THREE.BoxGeometry(0.5, 0.1, 0.06), std('#101218', { roughness: 0.2 }));
      bar.position.set(0, 0.03, 0.29); head.add(bar);
      for (const s of [-1, 1]) {
        const lens = part(new THREE.BoxGeometry(0.2, 0.14, 0.05), std('#0b0d14', { roughness: 0.1, metalness: 0.4 }));
        lens.position.set(s * 0.12, 0.03, 0.3); head.add(lens);
      }
      break;
    }
    case 'medic backpack': {
      const pack = part(new THREE.BoxGeometry(0.46, 0.55, 0.22), std('#d9342b'));
      pack.position.set(0, 0.05, -0.34); body.add(pack);
      const cross1 = part(new THREE.BoxGeometry(0.2, 0.06, 0.03), std('#ffffff'), false);
      const cross2 = part(new THREE.BoxGeometry(0.06, 0.2, 0.03), std('#ffffff'), false);
      cross1.position.set(0, 0.07, -0.46); cross2.position.copy(cross1.position);
      body.add(cross1, cross2);
      break;
    }
    case 'headphones': {
      const arc = part(new THREE.TorusGeometry(0.32, 0.04, 5, 14, Math.PI), std('#1e1e24'));
      arc.position.y = 0.04; arc.rotation.z = 0; head.add(arc);
      for (const s of [-1, 1]) {
        const cup = part(new THREE.CylinderGeometry(0.1, 0.1, 0.09, 8), std('#7a4fd1'));
        cup.rotation.z = Math.PI / 2; cup.position.set(s * 0.32, 0.02, 0); head.add(cup);
      }
      break;
    }
    case 'wide-brim hat': {
      const brim = part(new THREE.CylinderGeometry(0.62, 0.62, 0.04, 14), std('#d7b24a'));
      brim.position.y = 0.2; head.add(brim);
      const top = part(new THREE.CylinderGeometry(0.26, 0.31, 0.24, 10), std('#c9a23e'));
      top.position.y = 0.33; head.add(top);
      const ribbon = part(new THREE.CylinderGeometry(0.315, 0.315, 0.06, 10), std('#6b3a22'));
      ribbon.position.y = 0.25; head.add(ribbon);
      break;
    }
    case 'glasses and tie': {
      for (const s of [-1, 1]) {
        const rim = part(new THREE.TorusGeometry(0.075, 0.016, 5, 10), dark, false);
        rim.position.set(s * 0.12, 0.03, 0.3); head.add(rim);
      }
      const bridge = part(new THREE.BoxGeometry(0.1, 0.014, 0.014), dark, false);
      bridge.position.set(0, 0.04, 0.3); head.add(bridge);
      const tie = part(new THREE.ConeGeometry(0.075, 0.4, 4), std('#a0262c'));
      tie.rotation.x = Math.PI; tie.position.set(0, 0.0, 0.27); body.add(tie);
      break;
    }
    case 'scarf': {
      const ring = part(new THREE.TorusGeometry(0.25, 0.08, 6, 12), std('#2f9e5b'));
      ring.rotation.x = Math.PI / 2; ring.position.y = 0.36; body.add(ring);
      const tail = part(new THREE.BoxGeometry(0.14, 0.42, 0.05), std('#2f9e5b'));
      tail.position.set(0.14, 0.18, 0.25); body.add(tail);
      break;
    }
    case 'cap': {
      const dome = part(new THREE.SphereGeometry(0.33, 10, 7, 0, Math.PI * 2, 0, Math.PI / 2), std('#5a6628'));
      dome.position.y = 0.1; head.add(dome);
      const visor = part(new THREE.BoxGeometry(0.4, 0.04, 0.26), std('#4a5420'));
      visor.position.set(0, 0.12, 0.36); head.add(visor);
      break;
    }
  }
}

export class Character {
  group = new THREE.Group();
  readonly name: string;
  readonly color: string;
  private root = new THREE.Group();
  private body = new THREE.Group();
  private head = new THREE.Group();
  private legs: THREE.Mesh[] = [];
  private arms: THREE.Group[] = [];
  private ring: THREE.Mesh;
  private tagEl: HTMLDivElement;
  private energyEl: HTMLElement;
  private bubbleEl: HTMLDivElement;
  private bubbleObj: CSS2DObject;
  private x = 0;
  private z = 0;
  private yaw = 0;
  private walk: { fx: number; fz: number; tx: number; tz: number; start: number; dur: number } | null = null;
  private act_: { kind: ActKind; start: number; dur: number; dx: number; dz: number } | null = null;
  private phase = Math.random() * 6;
  private energy = 100;
  private moving = false;
  private tilt = 0;

  constructor(persona: Persona, index: number) {
    this.name = persona.name;
    this.color = persona.color;
    const skin = std(SKIN[index % SKIN.length]);
    const cloth = std(persona.color);
    const clothDark = std(new THREE.Color(persona.color).multiplyScalar(0.78).getStyle());

    const torso = part(new THREE.CapsuleGeometry(0.27, 0.5, 4, 8), cloth);
    torso.position.y = 0.98;
    this.body.add(torso);
    const hips = part(new THREE.CylinderGeometry(0.27, 0.27, 0.16, 10), std('#363a52'));
    hips.position.y = 0.62;
    this.body.add(hips);
    for (const s of [-1, 1]) {
      const leg = part(new THREE.CylinderGeometry(0.1, 0.09, 0.5, 6), std('#363a52'));
      leg.geometry.translate(0, -0.25, 0);
      leg.position.set(s * 0.14, 0.52, 0);
      this.legs.push(leg);
      this.group.add(leg);
      const shoe = part(new THREE.BoxGeometry(0.17, 0.09, 0.27), std('#2a2230'));
      shoe.position.set(0, -0.5, 0.04);
      leg.add(shoe);

      const arm = new THREE.Group();
      arm.position.set(s * 0.37, 1.22, 0);
      const upper = part(new THREE.CapsuleGeometry(0.075, 0.3, 3, 6), clothDark);
      upper.position.y = -0.2;
      const hand = part(new THREE.SphereGeometry(0.085, 6, 5), skin);
      hand.position.y = -0.43;
      arm.add(upper, hand);
      this.arms.push(arm);
      this.body.add(arm);
    }
    const headMesh = part(new THREE.SphereGeometry(0.3, 14, 10), skin);
    this.head.add(headMesh);
    this.head.position.y = 1.72;
    const hairM = std(HAIR[index % HAIR.length]);
    const hair = part(new THREE.SphereGeometry(0.315, 14, 8, 0, Math.PI * 2, 0, Math.PI * 0.55), hairM);
    hair.rotation.x = -0.25;
    hair.position.y = 0.03;
    this.head.add(hair);
    for (const s of [-1, 1]) {
      const eye = part(new THREE.SphereGeometry(0.038, 6, 5), std('#1a1a22'), false);
      eye.position.set(s * 0.1, 0.01, 0.275);
      this.head.add(eye);
    }
    const mouth = part(new THREE.BoxGeometry(0.08, 0.018, 0.02), std('#7a3a3a'), false);
    mouth.position.set(0, -0.1, 0.285);
    this.head.add(mouth);
    accessory(persona.accessory, this.head, this.body, persona.color);
    this.body.add(this.head);
    this.root.add(this.body);
    this.group.add(this.root);
    this.group.userData.character = this;

    this.ring = new THREE.Mesh(new THREE.RingGeometry(0.62, 0.78, 28), new THREE.MeshBasicMaterial({ color: '#ffffff', transparent: true, opacity: 0.9, side: THREE.DoubleSide, depthWrite: false }));
    this.ring.rotation.x = -Math.PI / 2;
    this.ring.position.y = 0.05;
    this.ring.visible = false;
    this.group.add(this.ring);

    this.tagEl = document.createElement('div');
    this.tagEl.className = 'tag';
    this.tagEl.innerHTML = `<i style="background:${persona.color}"></i><b>${persona.name}</b><em><u></u></em>`;
    this.energyEl = this.tagEl.querySelector('u') as HTMLElement;
    const tag = new CSS2DObject(this.tagEl);
    tag.position.set(0, 2.32, 0);
    this.group.add(tag);

    this.bubbleEl = document.createElement('div');
    this.bubbleEl.className = 'bubbles';
    this.bubbleObj = new CSS2DObject(this.bubbleEl);
    this.bubbleObj.position.set(0, 2.55, 0);
    this.group.add(this.bubbleObj);
    this.setEnergy(100);
  }

  get position() { return { x: this.x, z: this.z }; }

  placeAt(x: number, z: number) {
    this.x = x; this.z = z; this.walk = null; this.moving = false;
  }

  walkTo(x: number, z: number, start: number, dur: number) {
    if (Math.hypot(x - this.x, z - this.z) < 0.05) return;
    this.walk = { fx: this.x, fz: this.z, tx: x, tz: z, start, dur: Math.max(0.2, dur) };
  }

  act(kind: ActKind, start: number, dur: number, towards?: { x: number; z: number }) {
    const dx = towards ? towards.x - this.x : 0, dz = towards ? towards.z - this.z : 0;
    this.act_ = { kind, start, dur, dx, dz };
  }

  setSelected(on: boolean) {
    this.ring.visible = on;
    this.tagEl.classList.toggle('sel', on);
  }

  setEnergy(e: number) {
    this.energy = e;
    this.energyEl.style.width = `${Math.max(0, Math.min(100, e))}%`;
    this.tagEl.classList.toggle('tired', e < 25);
  }

  say(text: string, channel: string, lifeMs: number) {
    const el = document.createElement('div');
    const dm = channel.startsWith('dm:');
    el.className = 'bubble' + (dm ? ' dm' : '');
    el.textContent = (dm ? `🔒 → ${channel.slice(3)}: ` : '') + (text.length > 150 ? text.slice(0, 147) + '…' : text);
    this.bubbleEl.appendChild(el);
    while (this.bubbleEl.children.length > 2) this.bubbleEl.removeChild(this.bubbleEl.firstChild!);
    setTimeout(() => el.remove(), lifeMs);
  }

  floatText(text: string, cls = '') {
    const el = document.createElement('div');
    el.className = 'float ' + cls;
    el.textContent = text;
    const obj = new CSS2DObject(el);
    obj.position.set(0, 2.1, 0);
    this.group.add(obj);
    setTimeout(() => { this.group.remove(obj); el.remove(); }, 1900);
  }

  clearBubbles() { this.bubbleEl.innerHTML = ''; }

  update(time: number, dt: number) {
    let speed = 0;
    if (this.walk) {
      const w = this.walk;
      const p = (time - w.start) / w.dur;
      if (p >= 1) {
        this.x = w.tx; this.z = w.tz; this.walk = null;
      } else if (p > 0) {
        const e = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
        const nx = w.fx + (w.tx - w.fx) * e, nz = w.fz + (w.tz - w.fz) * e;
        const dx = nx - this.x, dz = nz - this.z;
        speed = Math.hypot(dx, dz) / Math.max(dt, 1e-3);
        if (Math.hypot(dx, dz) > 1e-4) this.yaw = lerpAngle(this.yaw, Math.atan2(dx, dz), Math.min(1, dt * 12));
        this.x = nx; this.z = nz;
      }
    }
    this.moving = speed > 0.4;

    const swing = this.moving ? Math.sin((time + this.phase) * 11) : 0;
    this.legs[0].rotation.x = swing * 0.7;
    this.legs[1].rotation.x = -swing * 0.7;
    let armL = -swing * 0.6, armR = swing * 0.6;
    let bob = this.moving ? Math.abs(Math.sin((time + this.phase) * 11)) * 0.07 : Math.sin((time + this.phase) * 2) * 0.012;
    let lean = this.moving ? 0.1 : 0;
    let squash = 1, hop = 0, offX = 0, offZ = 0, shake = 0;

    const a = this.act_;
    if (a) {
      const p = (time - a.start) / a.dur;
      if (p >= 1) this.act_ = null;
      else if (p >= 0) {
        const env = Math.sin(Math.min(1, p) * Math.PI);
        switch (a.kind) {
          case 'chop': armL = armR = -1.2 + Math.sin(p * 22) * 1.0; lean = 0.25; break;
          case 'hammer': armR = -1.4 + Math.sin(p * 26) * 1.1; armL = -0.5; lean = 0.15; break;
          case 'reach': armL = armR = -0.6 - env * 0.9; squash = 1 - env * 0.16; lean = env * 0.45; break;
          case 'sit': squash = 1 - env * 0.28; break;
          case 'give': armR = -1.5 * env; break;
          case 'wave': armR = -2.6 + Math.sin(p * 30) * 0.5; break;
          case 'hop': hop = env * 0.4; break;
          case 'lunge': {
            const len = Math.hypot(a.dx, a.dz) || 1;
            const k = Math.sin(Math.min(1, p * 1.6) * Math.PI) * 0.9;
            offX = (a.dx / len) * k; offZ = (a.dz / len) * k;
            armR = -1.8 * env; armL = -0.8 * env;
            if (len > 0.1) this.yaw = lerpAngle(this.yaw, Math.atan2(a.dx, a.dz), 0.5);
            break;
          }
          case 'flinch': shake = env; offX = Math.sin(p * 60) * 0.12 * env; break;
        }
      }
    }
    if (this.energy < 18) { lean += 0.22; bob *= 0.5; }

    this.tilt = lerp(this.tilt, lean, Math.min(1, dt * 10));
    this.arms[0].rotation.x = armL;
    this.arms[1].rotation.x = armR;
    this.body.rotation.x = this.tilt;
    this.body.scale.y = squash;
    this.body.position.y = bob + hop - (1 - squash) * 0.3;
    this.head.rotation.z = shake * Math.sin(time * 50) * 0.2;
    this.root.rotation.y = this.yaw;

    const px = this.x + offX, pz = this.z + offZ;
    this.group.position.set(px, walkHeight(px, pz) + hop * 0.5, pz);
    for (const l of this.legs) l.position.y = 0.52 + (squash < 1 ? -(1 - squash) * 0.25 : 0);
  }
}

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
function lerpAngle(a: number, b: number, t: number) {
  let d = ((b - a + Math.PI) % (Math.PI * 2)) - Math.PI;
  if (d < -Math.PI) d += Math.PI * 2;
  return a + d * t;
}
