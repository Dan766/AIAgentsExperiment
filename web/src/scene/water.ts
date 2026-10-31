import * as THREE from 'three';
import { SIZE, buildHeightTexture } from './terrain';

const vert = /* glsl */ `
  uniform float uTime;
  varying vec3 vWorld;
  void main() {
    vec3 p = position;
    float w = sin(p.x * 0.35 + uTime * 0.9) * 0.05 + sin(p.z * 0.45 - uTime * 0.7) * 0.05
            + sin((p.x + p.z) * 0.8 + uTime * 1.6) * 0.025;
    p.y += w;
    vec4 wp = modelMatrix * vec4(p, 1.0);
    vWorld = wp.xyz;
    gl_Position = projectionMatrix * viewMatrix * wp;
  }
`;

const frag = /* glsl */ `
  uniform float uTime;
  uniform float uSize;
  uniform sampler2D uHeight;
  uniform vec3 uShallow;
  uniform vec3 uDeep;
  uniform vec3 uSunColor;
  uniform vec3 uSunDir;
  uniform float uLight;
  uniform vec3 uFog;
  uniform float uFogNear;
  uniform float uFogFar;
  varying vec3 vWorld;

  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y);
  }

  void main() {
    vec2 uv = vWorld.xz / uSize + 0.5;
    float h = texture2D(uHeight, uv).r * 9.0 - 3.0;
    float depth = max(0.0, -h);
    float shallow = smoothstep(0.0, 2.2, depth);
    vec3 col = mix(uShallow, uDeep, shallow);

    // moving caustic-ish ripples
    float r = noise(vWorld.xz * 0.9 + vec2(uTime * 0.25, -uTime * 0.18)) * 0.6 + noise(vWorld.xz * 2.1 - vec2(uTime * 0.4, uTime * 0.3)) * 0.4;
    col += (r - 0.5) * 0.10;

    // shoreline foam: bands that breathe in and out
    float wobble = 0.16 + 0.12 * sin(uTime * 1.2 + vWorld.x * 0.6 + vWorld.z * 0.5) + 0.05 * noise(vWorld.xz * 3.0 + uTime * 0.5);
    float foam = smoothstep(wobble + 0.18, wobble, depth) * smoothstep(-0.08, 0.02, depth);
    foam += smoothstep(0.55, 0.45, abs(depth - 0.55 - 0.15 * sin(uTime * 1.0 + vWorld.x))) * 0.18 * noise(vWorld.xz * 4.0 - uTime * 0.3);
    col = mix(col, vec3(1.0), clamp(foam, 0.0, 0.95));

    // sun glitter
    vec3 viewDir = normalize(cameraPosition - vWorld);
    vec3 n = normalize(vec3((noise(vWorld.xz * 1.3 + uTime * 0.5) - 0.5) * 0.5, 1.0, (noise(vWorld.xz * 1.3 - uTime * 0.4 + 9.0) - 0.5) * 0.5));
    float spec = pow(max(dot(reflect(-uSunDir, n), viewDir), 0.0), 120.0);
    col += uSunColor * spec * 1.4 * max(uSunDir.y, 0.0);

    col *= uLight;
    float alpha = mix(0.55, 1.0, smoothstep(0.0, 0.85, shallow));
    alpha = max(alpha, foam);

    float dist = length(cameraPosition - vWorld);
    float fogF = smoothstep(uFogNear, uFogFar, dist);
    gl_FragColor = vec4(mix(col, uFog, fogF), alpha);
  }
`;

export class Water {
  mesh: THREE.Mesh;
  mat: THREE.ShaderMaterial;
  constructor() {
    this.mat = new THREE.ShaderMaterial({
      vertexShader: vert,
      fragmentShader: frag,
      transparent: true,
      depthWrite: false,
      uniforms: {
        uTime: { value: 0 },
        uSize: { value: SIZE },
        uHeight: { value: buildHeightTexture() },
        uShallow: { value: new THREE.Color('#5fd1c7') },
        uDeep: { value: new THREE.Color('#1c6fa8') },
        uSunColor: { value: new THREE.Color('#ffffff') },
        uSunDir: { value: new THREE.Vector3(0, 1, 0) },
        uLight: { value: 1 },
        uFog: { value: new THREE.Color('#bfe3ff') },
        uFogNear: { value: 70 },
        uFogFar: { value: 220 },
      },
    });
    const geo = new THREE.PlaneGeometry(520, 520, 160, 160);
    geo.rotateX(-Math.PI / 2);
    this.mesh = new THREE.Mesh(geo, this.mat);
    this.mesh.renderOrder = 1;
  }
  update(t: number) {
    this.mat.uniforms.uTime.value = t;
  }
}
