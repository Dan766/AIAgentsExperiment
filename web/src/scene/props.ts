import * as THREE from 'three';
import { ANCHORS, heightAt, seeded } from './terrain';

const mat = (color: string, extra: Partial<THREE.MeshStandardMaterialParameters> = {}) =>
  new THREE.MeshStandardMaterial({ color, flatShading: true, roughness: 0.9, ...extra });

function mesh(geo: THREE.BufferGeometry, m: THREE.Material, shadow = true) {
  const o = new THREE.Mesh(geo, m);
  o.castShadow = shadow;
  o.receiveShadow = true;
  return o;
}

export function palm(rnd: () => number): THREE.Group {
  const g = new THREE.Group();
  const trunkM = mat('#a9834d');
  const height = 3.2 + rnd() * 2.2;
  const bend = (rnd() - 0.5) * 1.1;
  const segs = 6;
  let x = 0, y = 0;
  for (let i = 0; i < segs; i++) {
    const h = height / segs;
    const t = mesh(new THREE.CylinderGeometry(0.2 - i * 0.017, 0.23 - i * 0.017, h * 1.05, 6), trunkM);
    t.position.set(x, y + h / 2, 0);
    t.rotation.z = -bend * 0.12;
    g.add(t);
    x += Math.sin(bend * 0.12) * h * 0.9 * (bend > 0 ? 1 : 1);
    y += h * 0.98;
  }
  const crown = new THREE.Group();
  crown.position.set(x, y, 0);
  const leafM = [mat('#3f9b49'), mat('#4aa852'), mat('#368c42')];
  const n = 8;
  for (let i = 0; i < n; i++) {
    const leaf = mesh(new THREE.ConeGeometry(0.36, 2.5, 4), leafM[i % 3]);
    leaf.scale.set(1, 1, 0.22);
    leaf.geometry.translate(0, 1.25, 0);
    const pivot = new THREE.Group();
    pivot.rotation.y = (i / n) * Math.PI * 2 + rnd() * 0.3;
    leaf.rotation.z = -1.15 - rnd() * 0.25;
    pivot.add(leaf);
    crown.add(pivot);
  }
  const nut = mesh(new THREE.SphereGeometry(0.2, 6, 5), mat('#5a3d1e'));
  nut.position.set(0.15, -0.1, 0.1);
  crown.add(nut);
  g.add(crown);
  g.userData.crown = crown;
  g.rotation.y = rnd() * Math.PI * 2;
  return g;
}

export function rock(rnd: () => number, size = 1): THREE.Mesh {
  const m = mesh(new THREE.DodecahedronGeometry(1, 0), mat(rnd() > 0.5 ? '#8d867a' : '#7c776d'));
  m.scale.set(size * (0.8 + rnd() * 0.6), size * (0.55 + rnd() * 0.4), size * (0.8 + rnd() * 0.6));
  m.rotation.set(rnd() * 3, rnd() * 3, rnd() * 3);
  return m;
}

export function campfire(): { group: THREE.Group; flames: THREE.Mesh[]; light: THREE.PointLight } {
  const g = new THREE.Group();
  const logM = mat('#6b4a2a');
  for (let i = 0; i < 4; i++) {
    const l = mesh(new THREE.CylinderGeometry(0.1, 0.1, 1.1, 6), logM);
    l.rotation.z = Math.PI / 2;
    l.rotation.y = (i / 4) * Math.PI;
    l.position.y = 0.12;
    g.add(l);
  }
  const rnd = seeded(3);
  for (let i = 0; i < 9; i++) {
    const a = (i / 9) * Math.PI * 2;
    const s = rock(rnd, 0.2);
    s.position.set(Math.cos(a) * 0.85, 0.08, Math.sin(a) * 0.85);
    g.add(s);
  }
  const flames: THREE.Mesh[] = [];
  const colors = ['#ff7a1a', '#ffb02e', '#ffe27a'];
  colors.forEach((c, i) => {
    const f = new THREE.Mesh(new THREE.ConeGeometry(0.34 - i * 0.08, 1.0 - i * 0.18, 5), new THREE.MeshBasicMaterial({ color: c, transparent: true, opacity: 0.92 }));
    f.position.y = 0.55 - i * 0.04;
    g.add(f);
    flames.push(f);
  });
  const light = new THREE.PointLight('#ff8a3c', 14, 16, 1.6);
  light.position.y = 1.1;
  g.add(light);
  return { group: g, flames, light };
}

export function tent(color: string): THREE.Group {
  const g = new THREE.Group();
  const body = mesh(new THREE.ConeGeometry(1.35, 1.7, 4), mat(color));
  body.rotation.y = Math.PI / 4;
  body.position.y = 0.85;
  g.add(body);
  const door = mesh(new THREE.PlaneGeometry(0.5, 0.9), mat('#2b2118', { side: THREE.DoubleSide }), false);
  door.position.set(0, 0.45, 0.67);
  g.add(door);
  return g;
}

export function crate(color = '#a8793f'): THREE.Mesh {
  const c = mesh(new THREE.BoxGeometry(0.62, 0.5, 0.62), mat(color));
  return c;
}

export function lookout(): THREE.Group {
  const g = new THREE.Group();
  const wood = mat('#8a5f35');
  const plat = mesh(new THREE.BoxGeometry(2.6, 0.16, 2.6), wood);
  plat.position.y = 0.9;
  g.add(plat);
  for (const [x, z] of [[-1.1, -1.1], [1.1, -1.1], [-1.1, 1.1], [1.1, 1.1]]) {
    const p = mesh(new THREE.CylinderGeometry(0.09, 0.11, 2.3, 5), wood);
    p.position.set(x, 1.1, z);
    g.add(p);
  }
  const roof = mesh(new THREE.ConeGeometry(2.1, 0.9, 4), mat('#c8502f'));
  roof.rotation.y = Math.PI / 4;
  roof.position.y = 2.6;
  g.add(roof);
  const pole = mesh(new THREE.CylinderGeometry(0.04, 0.04, 2.2, 4), mat('#d9d2c4'));
  pole.position.set(1.0, 3.3, 1.0);
  g.add(pole);
  const flag = mesh(new THREE.PlaneGeometry(0.9, 0.5), mat('#e24a4a', { side: THREE.DoubleSide }), false);
  flag.position.set(1.45, 4.1, 1.0);
  g.add(flag);
  g.userData.flag = flag;
  return g;
}

export function dock(): THREE.Group {
  const g = new THREE.Group();
  const wood = mat('#9a6d3f');
  for (let i = 0; i < 9; i++) {
    const p = mesh(new THREE.BoxGeometry(1.5, 0.08, 0.28), wood);
    p.position.set(i * 0.34, 0, 0);
    p.rotation.y = Math.PI / 2;
    g.add(p);
  }
  for (let i = 0; i < 4; i++) {
    for (const s of [-0.7, 0.7]) {
      const post = mesh(new THREE.CylinderGeometry(0.07, 0.07, 1.2, 5), wood);
      post.position.set(i * 0.9, -0.35, s);
      g.add(post);
    }
  }
  return g;
}

export function wreck(): THREE.Group {
  const g = new THREE.Group();
  const dark = mat('#5b4129'), mid = mat('#7a5a38'), sailM = mat('#d8cdb6', { side: THREE.DoubleSide });
  // broken hull: two raked sides and a keel
  const keel = mesh(new THREE.BoxGeometry(5.2, 0.28, 0.5), dark);
  keel.position.y = 0.2;
  g.add(keel);
  for (const s of [-1, 1]) {
    const side = mesh(new THREE.BoxGeometry(4.6, 1.5, 0.18), mid);
    side.position.set(s * 0.2 - 0.3, 0.95, s * 0.95);
    side.rotation.x = s * -0.32;
    side.rotation.z = 0.05 * s;
    g.add(side);
  }
  for (let i = 0; i < 6; i++) {
    const rib = mesh(new THREE.BoxGeometry(0.14, 1.5, 1.9), dark);
    rib.position.set(-2.2 + i * 0.85, 0.95, 0);
    rib.scale.y = 0.55 + (i % 3) * 0.25;
    g.add(rib);
  }
  const mast = mesh(new THREE.CylinderGeometry(0.1, 0.14, 4.4, 6), dark);
  mast.position.set(0.4, 2.3, 0);
  mast.rotation.z = 0.5;
  g.add(mast);
  const sail = mesh(new THREE.PlaneGeometry(1.8, 1.7, 3, 3), sailM, false);
  sail.position.set(-0.55, 3.3, 0.05);
  sail.rotation.set(0.1, 0.2, 0.5);
  g.add(sail);
  g.rotation.set(0.04, 0.5, -0.12);
  return g;
}

export function scatterIsland(): { group: THREE.Group; palms: THREE.Group[] } {
  const g = new THREE.Group();
  const rnd = seeded(11);
  const palms: THREE.Group[] = [];
  const keepClear = Object.values(ANCHORS).map((a) => ({ ...a, r: 3.6 }));
  const clear = (x: number, z: number, pad = 0) => keepClear.every((a) => Math.hypot(x - a.x, z - a.z) > a.r + pad);

  // dense forest around the forest anchor, sparser palms along the beaches
  let placed = 0;
  for (let tries = 0; tries < 900 && placed < 42; tries++) {
    const x = (rnd() - 0.5) * 44, z = (rnd() - 0.5) * 44;
    const h = heightAt(x, z);
    const inForest = Math.hypot(x + 6, z + 4) < 8;
    if (h < 0.45 || h > 3.4 || !clear(x, z, 0.4)) continue;
    if (!inForest && rnd() > 0.14) continue;
    const p = palm(rnd);
    p.position.set(x, h - 0.05, z);
    const s = 0.72 + rnd() * 0.42;
    p.scale.setScalar(s);
    g.add(p);
    palms.push(p);
    placed++;
  }
  for (let tries = 0, n = 0; tries < 500 && n < 34; tries++) {
    const x = (rnd() - 0.5) * 50, z = (rnd() - 0.5) * 50;
    const h = heightAt(x, z);
    if (h < -0.35 || h > 5 || !clear(x, z, 0.2)) continue;
    const r = rock(rnd, 0.35 + rnd() * (h > 2.8 ? 1.1 : 0.55));
    r.position.set(x, h + 0.1, z);
    g.add(r);
    n++;
  }
  // tufts of grass-colored cones for texture
  const tuftM = mat('#4f9a3f');
  for (let tries = 0, n = 0; tries < 800 && n < 120; tries++) {
    const x = (rnd() - 0.5) * 40, z = (rnd() - 0.5) * 40;
    const h = heightAt(x, z);
    if (h < 1.2 || h > 3.3 || !clear(x, z)) continue;
    const t = mesh(new THREE.ConeGeometry(0.13, 0.5, 4), tuftM, false);
    t.position.set(x, h + 0.2, z);
    t.rotation.y = rnd() * 3;
    g.add(t);
    n++;
  }
  return { group: g, palms };
}
