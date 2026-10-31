import * as THREE from 'three';

export const SIZE = 84;

const hash = (x: number, z: number) => {
  const s = Math.sin(x * 127.1 + z * 311.7) * 43758.5453;
  return s - Math.floor(s);
};
function vnoise(x: number, z: number) {
  const xi = Math.floor(x), zi = Math.floor(z);
  const xf = x - xi, zf = z - zi;
  const u = xf * xf * (3 - 2 * xf), v = zf * zf * (3 - 2 * zf);
  const a = hash(xi, zi), b = hash(xi + 1, zi), c = hash(xi, zi + 1), d = hash(xi + 1, zi + 1);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}
const fbm = (x: number, z: number) =>
  0.5 * vnoise(x * 0.35, z * 0.35) + 0.3 * vnoise(x * 0.8 + 7, z * 0.8 - 3) + 0.2 * vnoise(x * 1.7, z * 1.7);
const smooth = (a: number, b: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

export const ANCHORS: Record<string, { x: number; z: number }> = {
  camp: { x: 0, z: 14.5 },
  build_site: { x: 14, z: 8 },
  forest: { x: -6, z: -4 },
  wreck: { x: 17.5, z: 11.5 },
  lagoon: { x: -8.4, z: 3.2 },
  lookout: { x: 3, z: -11.5 },
};

/** Ground height at (x, z). Water sits at y = 0. */
export function heightAt(x: number, z: number): number {
  const d = Math.hypot(x / 1.1, z / 0.95);
  const base = 1 - smooth(10, 21, d);
  let h = base * 2.6 - 0.7 + (fbm(x, z) - 0.5) * 1.4 * base;
  h += 4.2 * Math.exp(-((x - 3) ** 2 + (z + 13) ** 2) / 20); // cliffs
  h -= 2.8 * Math.exp(-((x + 11.5) ** 2 + (z - 1.5) ** 2) / 10); // lagoon pool
  const reef = 1.45 * Math.exp(-((x - 17.5) ** 2 + (z - 11.5) ** 2) / 26) - 1.55;
  return Math.max(h, reef, -3);
}

/** Where a character can stand: never below the waterline (they wade through shallows). */
export const walkHeight = (x: number, z: number) => Math.max(heightAt(x, z), -0.22);

const C = {
  deepSand: new THREE.Color('#bfa56b'),
  sand: new THREE.Color('#ecdca6'),
  wetSand: new THREE.Color('#d6c389'),
  grassA: new THREE.Color('#78b852'),
  grassB: new THREE.Color('#5e9f46'),
  grassC: new THREE.Color('#4f8c3e'),
  rock: new THREE.Color('#8d867a'),
  rockHi: new THREE.Color('#a7a093'),
};

function colorFor(h: number, slope: number, n: number): THREE.Color {
  const c = new THREE.Color();
  if (h < -0.1) c.copy(C.deepSand);
  else if (h < 0.25) c.copy(C.wetSand);
  else if (h < 0.85) c.lerpColors(C.wetSand, C.sand, smooth(0.25, 0.55, h));
  else if (h < 1.25) c.lerpColors(C.sand, C.grassA, smooth(0.85, 1.25, h));
  else c.lerpColors(C.grassA, n > 0.5 ? C.grassB : C.grassC, Math.min(1, (h - 1.25) / 1.5 + n * 0.3));
  if (h > 3.2 || slope > 0.9) c.lerp(h > 5 ? C.rockHi : C.rock, Math.min(1, Math.max(smooth(3.0, 4.2, h), (slope - 0.7) * 1.6)));
  const v = 0.94 + n * 0.12; // facet-to-facet variation keeps the low-poly look alive
  return c.multiplyScalar(v);
}

export function buildTerrain(): THREE.Mesh {
  const seg = 130;
  const geo = new THREE.PlaneGeometry(SIZE, SIZE, seg, seg);
  geo.rotateX(-Math.PI / 2);
  const pos = geo.attributes.position;
  for (let i = 0; i < pos.count; i++) pos.setY(i, heightAt(pos.getX(i), pos.getZ(i)));
  const flat = geo.toNonIndexed();
  const p = flat.attributes.position;
  const colors = new Float32Array(p.count * 3);
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
  for (let i = 0; i < p.count; i += 3) {
    a.fromBufferAttribute(p, i); b.fromBufferAttribute(p, i + 1); c.fromBufferAttribute(p, i + 2);
    const n = new THREE.Vector3().crossVectors(b.clone().sub(a), c.clone().sub(a)).normalize();
    const h = (a.y + b.y + c.y) / 3;
    const col = colorFor(h, 1 - Math.abs(n.y), hash(a.x * 3.1, a.z * 3.7));
    for (let k = 0; k < 3; k++) col.toArray(colors, (i + k) * 3);
  }
  flat.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  flat.computeVertexNormals();
  const mesh = new THREE.Mesh(flat, new THREE.MeshStandardMaterial({ vertexColors: true, flatShading: true, roughness: 0.95 }));
  mesh.receiveShadow = true;
  mesh.castShadow = true;
  return mesh;
}

/** Height texture the water shader samples to find shorelines (R = (h + 3) / 9). */
export function buildHeightTexture(): THREE.DataTexture {
  const n = 192;
  const data = new Uint8Array(n * n);
  for (let j = 0; j < n; j++)
    for (let i = 0; i < n; i++) {
      const x = (i / (n - 1) - 0.5) * SIZE, z = (j / (n - 1) - 0.5) * SIZE;
      data[j * n + i] = Math.round(Math.min(1, Math.max(0, (heightAt(x, z) + 3) / 9)) * 255);
    }
  const tex = new THREE.DataTexture(data, n, n, THREE.RedFormat, THREE.UnsignedByteType);
  tex.magFilter = tex.minFilter = THREE.LinearFilter;
  tex.wrapS = tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.needsUpdate = true;
  return tex;
}

export function seeded(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}
