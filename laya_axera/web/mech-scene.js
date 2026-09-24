import * as T from "./vendor/three.module.js";

const C = { blue: 0x55dffe, red: 0xff625c, steel: 0x364351, white: 0xc8d8df };
const clamp = T.MathUtils.clamp;

function material(color, extra = {}) {
  return new T.MeshStandardMaterial({
    color,
    roughness: 0.52,
    metalness: 0.58,
    ...extra,
  });
}
function glow(color) {
  return material(color, { emissive: color, emissiveIntensity: 2 });
}
// Merge static parts by material; articulated joint groups stay independent.
function batchStatic(group) {
  for (const child of [...group.children])
    if (child.isGroup) batchStatic(child);
  const buckets = new Map();
  for (const child of group.children)
    if (child.isMesh && !Array.isArray(child.material)) {
      const parts = buckets.get(child.material) || [];
      parts.push(child);
      buckets.set(child.material, parts);
    }
  for (const [mat, parts] of buckets) {
    if (parts.length < 2) continue;
    const attributes = { position: [], normal: [], uv: [] };
    for (const part of parts) {
      part.updateMatrix();
      const geometry = part.geometry.index
        ? part.geometry.toNonIndexed()
        : part.geometry.clone();
      geometry.applyMatrix4(part.matrix);
      for (const name of Object.keys(attributes))
        attributes[name].push(...geometry.getAttribute(name).array);
      geometry.dispose();
      part.geometry.dispose();
      group.remove(part);
    }
    const geometry = new T.BufferGeometry();
    for (const [name, values] of Object.entries(attributes))
      geometry.setAttribute(
        name,
        new T.Float32BufferAttribute(values, name === "uv" ? 2 : 3),
      );
    const mesh = new T.Mesh(geometry, mat);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    group.add(mesh);
  }
}
function box(parent, w, h, d, x, y, z, mat) {
  const mesh = new T.Mesh(new T.BoxGeometry(w, h, d), mat);
  mesh.position.set(x, y, z);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  parent.add(mesh);
  return mesh;
}
function cylinder(parent, rt, rb, h, x, y, z, mat, segments = 12) {
  const mesh = new T.Mesh(new T.CylinderGeometry(rt, rb, h, segments), mat);
  mesh.position.set(x, y, z);
  mesh.castShadow = true;
  parent.add(mesh);
  return mesh;
}
function label(text, color) {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 96;
  const c = canvas.getContext("2d");
  c.font = "600 29px sans-serif";
  c.textAlign = "center";
  c.fillStyle = color;
  c.fillText(text, 256, 52);
  const map = new T.CanvasTexture(canvas);
  map.colorSpace = T.SRGBColorSpace;
  const sprite = new T.Sprite(
    new T.SpriteMaterial({ map, transparent: true, depthTest: false }),
  );
  sprite.scale.set(4.8, 0.9, 1);
  return sprite;
}
function shieldTexture() {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 256;
  const c = canvas.getContext("2d");
  c.strokeStyle = "rgba(95,236,255,0.65)";
  c.lineWidth = 1.5;
  c.fillStyle = "rgba(10,132,188,0.12)";
  c.fillRect(0, 0, 256, 256);
  for (let row = -1; row < 12; row++)
    for (let col = -1; col < 12; col++) {
      const x = col * 27 + (row % 2) * 13.5,
        y = row * 23.4;
      c.beginPath();
      for (let i = 0; i < 6; i++) {
        const a = (i * Math.PI) / 3 + Math.PI / 6;
        const px = x + 15.6 * Math.cos(a),
          py = y + 15.6 * Math.sin(a);
        if (i) c.lineTo(px, py);
        else c.moveTo(px, py);
      }
      c.closePath();
      c.stroke();
    }
  const map = new T.CanvasTexture(canvas);
  map.wrapS = map.wrapT = T.RepeatWrapping;
  map.repeat.set(3, 2);
  return map;
}

function robot(enemy = false) {
  const root = new T.Group(),
    body = new T.Group();
  root.add(body);
  const accent = enemy ? C.red : C.blue;
  const armor = material(enemy ? 0x873a37 : C.white);
  const dark = material(0x18212e),
    steel = material(C.steel),
    light = glow(accent);
  // Original articulated training mech, facing local +Z.
  box(body, 1.28, 1.12, 0.78, 0, 2.3, 0, armor);
  const chest = box(body, 0.82, 0.4, 0.12, 0, 2.43, 0.46, steel);
  chest.rotation.x = -0.16;
  box(body, 0.56, 0.065, 0.05, 0, 2.49, 0.55, light);
  box(body, 0.54, 0.15, 0.13, 0, 2.06, 0.47, dark);
  box(body, 1.08, 0.35, 0.62, 0, 1.62, 0, steel);
  box(body, 0.7, 0.5, 0.6, 0, 3.07, 0.07, armor);
  box(body, 0.55, 0.12, 0.08, 0, 3.1, 0.41, light);
  box(body, 0.38, 0.17, 0.08, 0, 2.91, 0.42, dark);
  box(body, 0.065, 0.53, 0.065, -0.37, 3.44, -0.08, steel);
  box(body, 0.9, 0.78, 0.34, 0, 2.32, -0.62, dark);
  for (const x of [-0.31, 0.31])
    cylinder(body, 0.15, 0.2, 0.55, x, 2.23, -0.85, steel);
  const arms = [],
    legs = [];
  for (const side of [-1, 1]) {
    const arm = new T.Group();
    arm.position.set(side * 0.92, 2.6, 0);
    body.add(arm);
    arms.push(arm);
    const shoulder = box(arm, 0.64, 0.46, 0.88, 0, 0, 0, armor);
    shoulder.rotation.z = side * -0.13;
    box(arm, 0.44, 0.64, 0.42, 0, -0.45, 0, dark);
    box(arm, 0.49, 0.61, 0.58, 0, -0.78, 0.24, armor);
    box(arm, 0.34, 0.26, 0.3, 0, -1.14, 0.35, steel);
    box(arm, 0.36, 0.045, 0.04, 0, -0.86, 0.56, light);
    const leg = new T.Group();
    leg.position.set(side * 0.37, 1.48, 0);
    body.add(leg);
    legs.push(leg);
    box(leg, 0.51, 0.63, 0.55, 0, -0.28, 0, steel);
    box(leg, 0.57, 0.38, 0.23, 0, -0.54, 0.33, armor);
    box(leg, 0.6, 0.57, 0.65, 0, -0.95, 0.01, armor);
    box(leg, 0.34, 0.065, 0.035, 0, -0.83, 0.36, light);
    box(leg, 0.64, 0.28, 0.96, 0, -1.35, 0.16, dark);
  }
  // Right arm energy cannon. Point toward +Z, not a cosmetic light beam.
  const gun = new T.Group();
  gun.position.set(0, -0.75, 0.75);
  arms[0].add(gun);
  box(gun, 0.36, 0.34, 1.12, 0, 0, 0, steel);
  box(gun, 0.22, 0.22, 0.18, 0, 0, 0.61, light);
  for (const x of [-0.15, 0.15]) box(gun, 0.035, 0.04, 0.78, x, 0.15, 0, light);
  const dome = new T.Mesh(
    new T.SphereGeometry(2.05, 32, 20),
    new T.MeshBasicMaterial({
      color: C.blue,
      map: shieldTexture(),
      transparent: true,
      opacity: 0.28,
      blending: T.AdditiveBlending,
      side: T.DoubleSide,
      depthWrite: false,
    }),
  );
  dome.position.y = 1.8;
  dome.scale.y = 1.1;
  dome.visible = false;
  root.add(dome);
  const rim = new T.Mesh(
    new T.RingGeometry(1.45, 1.5, 48),
    new T.MeshBasicMaterial({
      color: accent,
      transparent: true,
      opacity: 0.5,
      side: T.DoubleSide,
    }),
  );
  rim.rotation.x = -Math.PI / 2;
  rim.position.y = 0.025;
  root.add(rim);
  const name = label(
    enemy ? "TARGET // 训练对手" : "LAYA-01 // 你的机甲",
    enemy ? "#ff9690" : "#8deaff",
  );
  name.position.y = 4.15;
  root.add(name);
  const hp = new T.Group();
  hp.position.set(0, 3.73, 0);
  root.add(hp);
  box(hp, 1.4, 0.055, 0.04, 0, 0, 0, dark);
  const health = box(hp, 1.4, 0.055, 0.05, 0, 0, 0.02, light);
  batchStatic(body);
  return { root, body, legs, arms, dome, rim, hp, health, accent };
}

class FlatArena {
  constructor(canvas, report) {
    const replacement = canvas.cloneNode();
    canvas.replaceWith(replacement);
    this.canvas = replacement;
    this.ctx = replacement.getContext("2d");
    this.report = report;
    this.frames = 0;
    this.started = performance.now();
    this.mode = "2D 兼容模式";
    this.loop = this.loop.bind(this);
    requestAnimationFrame(this.loop);
  }
  update(state) {
    this.state = state;
  }
  setQuality() {}
  toggleCamera() {}
  loop(now) {
    requestAnimationFrame(this.loop);
    if (document.hidden) {
      this.started = now;
      this.frames = 0;
      return;
    }
    const canvas = this.canvas,
      c = this.ctx,
      rect = canvas.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;
    const w = canvas.width,
      h = canvas.height,
      scale = Math.min(w / 36, (h - 110) / 27);
    c.fillStyle = "#101c28";
    c.fillRect(0, 0, w, h);
    if (!this.state) return;
    c.save();
    c.translate(w / 2, h / 2 + 10);
    c.scale(scale, scale);
    c.strokeStyle = "#273745";
    c.lineWidth = 0.025;
    for (let x = -16; x <= 16; x += 2) {
      c.beginPath();
      c.moveTo(x, -12);
      c.lineTo(x, 12);
      c.stroke();
    }
    for (let z = -12; z <= 12; z += 2) {
      c.beginPath();
      c.moveTo(-16, z);
      c.lineTo(16, z);
      c.stroke();
    }
    for (const b of this.state.covers) {
      c.fillStyle = "#687681";
      c.fillRect(b.x - b.w / 2, b.z - b.d / 2, b.w, b.d);
    }
    for (const [r, color] of [
      [this.state.player, "#66deff"],
      ...this.state.enemies.map((e) => [e, "#ff6964"]),
    ]) {
      if (r.armor <= 0) continue;
      c.save();
      c.translate(r.x, r.z);
      c.rotate(-r.yaw);
      c.fillStyle = color;
      c.fillRect(-0.65, -0.7, 1.3, 1.4);
      c.fillRect(-0.2, 0.7, 0.4, 0.6);
      c.restore();
    }
    const p = this.state.player;
    if (p.shield) {
      c.strokeStyle = "#66ecff";
      c.lineWidth = 0.09;
      c.beginPath();
      c.arc(p.x, p.z, 1.7, 0, Math.PI * 2);
      c.stroke();
    }
    for (const s of this.state.projectiles) {
      c.fillStyle = s.team === "player" ? "#75e9ff" : "#ff9b62";
      c.fillRect(s.x - 0.1, s.z - 0.1, 0.2, 0.2);
    }
    c.restore();
    this.frames++;
    if (now - this.started > 2000) {
      this.report({
        mode: "2d",
        fps: (this.frames * 1000) / (now - this.started),
        width: w,
        height: h,
        frames: this.frames,
        quality: "low",
      });
      this.frames = 0;
      this.started = now;
    }
  }
}

export class ArenaRenderer {
  constructor(canvas, report, sound) {
    this.report = report;
    this.sound = sound;
    this.canvas = canvas;
    try {
      this.renderer = new T.WebGLRenderer({
        canvas,
        antialias: true,
        powerPreference: "high-performance",
      });
    } catch (e) {
      console.warn("WebGL2 unavailable, using labelled 2D fallback.", e);
      return new FlatArena(canvas, report);
    }
    this.renderer.outputColorSpace = T.SRGBColorSpace;
    this.renderer.toneMapping = T.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.25;
    this.renderer.shadowMap.type = T.PCFSoftShadowMap;
    this.renderer.shadowMap.autoUpdate = false;
    this.scene = new T.Scene();
    this.scene.background = new T.Color(0x09121d);
    this.scene.fog = new T.FogExp2(0x09121d, 0.013);
    this.camera = new T.PerspectiveCamera(43, 1, 0.1, 150);
    this.target = new T.Vector3(-0.8, 1, 0);
    this.theta = -0.38;
    this.phi = 1.04;
    this.radius = 27;
    this.quality = "balanced";
    this.robots = new Map();
    this.covers = new Map();
    this.bullets = new Map();
    this.particles = [];
    this.effectsSeen = new Set();
    this.pathLine = null;
    this.scene.add(new T.HemisphereLight(0xa8dbff, 0x293143, 2.5));
    this.sun = new T.DirectionalLight(0xd9eafa, 3.4);
    this.sun.position.set(-12, 26, 15);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(1024, 1024);
    Object.assign(this.sun.shadow.camera, {
      left: -23,
      right: 23,
      top: 23,
      bottom: -23,
      near: 1,
      far: 70,
    });
    this.sun.shadow.bias = -0.0005;
    this.scene.add(this.sun);
    const blue = new T.PointLight(0x22cfff, 60, 25, 2);
    blue.position.set(-12, 6, 0);
    this.scene.add(blue);
    const orange = new T.PointLight(0xff6a33, 45, 20, 2);
    orange.position.set(13, 5, -8);
    this.scene.add(orange);
    this.environment();
    batchStatic(this.scene);
    this.setQuality("balanced");
    this.controls();
    this.started = performance.now();
    this.lastFrame = this.started;
    this.frames = 0;
    this.loop = this.loop.bind(this);
    requestAnimationFrame(this.loop);
    canvas.addEventListener("webglcontextlost", (event) => {
      event.preventDefault();
      this.report({
        mode: "lost",
        fps: 0,
        width: canvas.width,
        height: canvas.height,
        frames: 0,
        quality: this.quality,
      });
    });
  }
  environment() {
    const floor = material(0x293743, { roughness: 0.82, metalness: 0.28 });
    box(this.scene, 37, 0.3, 29, 0, -0.18, 0, floor);
    const grid = new T.GridHelper(36, 36, 0x536574, 0x344959);
    grid.scale.z = 28 / 36;
    grid.position.y = -0.015;
    this.scene.add(grid);
    const steel = material(0x172431),
      edge = material(0x3d4e5c),
      cyan = glow(0x32a5ba),
      amber = material(0xca9941);
    for (const z of [-12.8, 12.8]) {
      box(this.scene, 34, 0.07, 0.08, 0, 0.025, z, cyan);
      box(this.scene, 37, 0.5, 0.75, 0, 0.2, z * 1.085, steel);
      for (let x = -16; x <= 16; x += 4)
        box(
          this.scene,
          1.2,
          0.015,
          0.18,
          x,
          0.01,
          z + (z > 0 ? -0.4 : 0.4),
          amber,
        );
    }
    for (const x of [-16.8, 16.8])
      box(this.scene, 0.07, 0.05, 25.6, x, 0.03, 0, cyan);
    // Hangar structure stays behind the action; foreground has an unobstructed view.
    box(this.scene, 39, 6.2, 0.7, 0, 3, -15, steel);
    for (let x = -18; x <= 18; x += 6) {
      box(this.scene, 0.75, 8, 1, x, 3.8, -15, edge);
      box(this.scene, 0.12, 4.5, 0.06, x + 0.5, 3, -14.45, cyan);
      box(this.scene, 4.8, 0.25, 0.9, x + 3, 6.4, -14.8, edge);
      for (let y = 1; y < 5; y += 1.2)
        box(this.scene, 4.9, 0.018, 0.03, x + 3, y, -14.61, edge);
    }
    const hangarName = label("AXERA / TRAINING SECTOR 01", "#a3b6c7");
    hangarName.position.set(0, 5.3, -14.3);
    hangarName.scale.set(10, 1.875, 1);
    this.scene.add(hangarName);
    for (const x of [-14.9, 14.9])
      for (const z of [-10.7, 10.7]) {
        cylinder(this.scene, 0.12, 0.18, 0.75, x, 0.4, z, edge);
        cylinder(this.scene, 0.13, 0.13, 0.16, x, 0.81, z, cyan);
      }
    const circle = new T.Mesh(
      new T.RingGeometry(5.9, 5.94, 96),
      new T.MeshBasicMaterial({ color: 0x51626d, side: T.DoubleSide }),
    );
    circle.rotation.x = -Math.PI / 2;
    circle.position.y = 0.01;
    this.scene.add(circle);
  }
  controls() {
    let drag = null;
    this.canvas.addEventListener("pointerdown", (e) => {
      drag = { x: e.clientX, y: e.clientY };
      this.canvas.setPointerCapture(e.pointerId);
    });
    this.canvas.addEventListener("pointermove", (e) => {
      if (!drag) return;
      this.theta -= (e.clientX - drag.x) * 0.005;
      this.phi = clamp(this.phi + (e.clientY - drag.y) * 0.004, 0.25, 1.32);
      drag = { x: e.clientX, y: e.clientY };
    });
    const end = () => {
      drag = null;
    };
    this.canvas.addEventListener("pointerup", end);
    this.canvas.addEventListener("pointercancel", end);
    this.canvas.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        this.radius = clamp(this.radius + e.deltaY * 0.018, 18, 54);
      },
      { passive: false },
    );
  }
  toggleCamera() {
    this.overview = !this.overview;
    this.phi = this.overview ? 0.35 : 1.04;
    this.radius = this.overview ? 40 : 27;
    this.theta = -0.38;
  }
  setQuality(value) {
    this.quality = value;
    const high = value === "high",
      low = value === "low";
    this.renderer.setPixelRatio(
      Math.min(window.devicePixelRatio || 1, high ? 2 : low ? 0.65 : 1.25),
    );
    this.renderer.shadowMap.enabled = !low;
    this.sun.castShadow = !low;
    this.renderer.shadowMap.needsUpdate = true;
    this.scene.traverse((object) => {
      if (object.isPointLight) object.visible = !low;
      if (!object.isMesh) return;
      if (
        object.material?.isMeshStandardMaterial &&
        !object.userData.originalMaterial
      ) {
        object.userData.originalMaterial = object.material;
        object.userData.fastMaterial = new T.MeshLambertMaterial({
          color: object.material.color,
          emissive: object.material.emissive,
          emissiveIntensity: object.material.emissiveIntensity,
        });
      }
      if (object.userData.originalMaterial)
        object.material = low
          ? object.userData.fastMaterial
          : object.userData.originalMaterial;
    });
  }
  disposeTree(root) {
    root.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) {
        for (const m of [o.material].flat()) {
          if (m.map) m.map.dispose();
          m.dispose();
        }
      }
      if (
        o.userData.originalMaterial &&
        o.material !== o.userData.originalMaterial
      )
        o.userData.originalMaterial.dispose();
      if (o.userData.fastMaterial && o.material !== o.userData.fastMaterial)
        o.userData.fastMaterial.dispose();
    });
    root.removeFromParent();
  }
  reset() {
    this.state = null;
    for (const r of this.robots.values()) this.disposeTree(r.root);
    for (const c of this.covers.values()) this.disposeTree(c);
    for (const s of this.bullets.values()) this.disposeTree(s);
    for (const p of this.particles) this.disposeTree(p.mesh);
    this.robots.clear();
    this.covers.clear();
    this.bullets.clear();
    this.particles = [];
    this.effectsSeen.clear();
    if (this.pathLine) {
      this.disposeTree(this.pathLine);
      this.pathLine = null;
    }
  }
  update(state, playing = false) {
    this.renderer.shadowMap.needsUpdate = true;
    if (
      !this.state ||
      state.time < this.state.time ||
      (state.time === 0 && !state.effects.length && this.state.event_count)
    )
      this.reset();
    const objectCount = this.robots.size + this.covers.size;
    this.previous = this.state;
    this.state = state;
    this.playing = playing;
    this.updated = performance.now();
    for (const [key, data] of [
      ["player", state.player],
      ...state.enemies.map((e) => ["enemy" + e.id, e]),
    ]) {
      if (!this.robots.has(key)) {
        const r = robot(key !== "player");
        r.root.scale.setScalar(1.2);
        this.robots.set(key, r);
        this.scene.add(r.root);
      }
      const r = this.robots.get(key);
      r.root.visible = data.armor > 0;
      r.health.scale.x = data.armor / (key === "player" ? 100 : 72);
      r.dome.visible = !!data.shield;
      r.hp.lookAt(this.camera.position);
    }
    for (const c of state.covers)
      if (!this.covers.has(c.id)) {
        const group = new T.Group();
        group.position.set(c.x, 0, c.z);
        const mat = material(0x63737d),
          dark = material(0x293744),
          yellow = material(0xe0aa48);
        box(group, c.w, 1.85, c.d, 0, 0.93, 0, mat);
        box(group, c.w + 0.12, 0.18, c.d + 0.1, 0, 1.84, 0, dark);
        for (const x of [-c.w / 2 + 0.15, c.w / 2 - 0.15])
          box(group, 0.17, 1.8, c.d + 0.06, x, 0.92, 0, dark);
        for (let x = -0.7; x < c.w / 2 - 0.3; x += 0.55) {
          const stripe = box(
            group,
            0.18,
            0.36,
            0.02,
            x,
            1.2,
            c.d / 2 + 0.025,
            yellow,
          );
          stripe.rotation.z = -0.45;
        }
        batchStatic(group);
        this.scene.add(group);
        this.covers.set(c.id, group);
      }
    const active = new Set(state.projectiles.map((s) => s.id));
    for (const [id, mesh] of this.bullets)
      if (!active.has(id)) {
        this.disposeTree(mesh);
        this.bullets.delete(id);
      }
    for (const s of state.projectiles)
      if (!this.bullets.has(s.id)) {
        const mesh = new T.Mesh(
          new T.CapsuleGeometry(0.065, 0.7, 2, 6),
          new T.MeshBasicMaterial({
            color: s.team === "player" ? 0x8af2ff : 0xff9559,
          }),
        );
        mesh.rotation.x = Math.PI / 2;
        mesh.rotation.z = -Math.atan2(s.vx, s.vz);
        this.scene.add(mesh);
        this.bullets.set(s.id, mesh);
      }
    for (const e of state.effects)
      if (!this.effectsSeen.has(e.id)) {
        this.effectsSeen.add(e.id);
        if (state.time - e.born < 0.35) {
          this.burst(e);
          this.sound?.(e.kind);
        }
      }
    if (this.effectsSeen.size > 512)
      this.effectsSeen = new Set(state.effects.map((e) => e.id));
    if (this.pathLine) {
      this.disposeTree(this.pathLine);
      this.pathLine = null;
    }
    if (state.path.length) {
      const points = [state.player, ...state.path].map(
        (p) => new T.Vector3(p.x, 0.06, p.z),
      );
      this.pathLine = new T.Line(
        new T.BufferGeometry().setFromPoints(points),
        new T.LineDashedMaterial({
          color: C.blue,
          dashSize: 0.35,
          gapSize: 0.25,
          transparent: true,
          opacity: 0.45,
        }),
      );
      this.pathLine.computeLineDistances();
      this.scene.add(this.pathLine);
    }
    // Apply the chosen shading mode to newly spawned mechs and cover too.
    if (
      this.quality === "low" &&
      this.robots.size + this.covers.size !== objectCount
    )
      this.setQuality("low");
  }
  burst(e) {
    const explosion = e.kind === "explosion",
      blue = ["shield", "muzzle_blue"].includes(e.kind);
    const count = this.quality === "low" ? 3 : explosion ? 24 : 8;
    for (let i = 0; i < count && this.particles.length < 180; i++) {
      const mesh = new T.Mesh(
        new T.SphereGeometry(explosion ? 0.14 : 0.045, 4, 3),
        new T.MeshBasicMaterial({
          color: blue ? 0x8cf3ff : 0xffb76b,
          transparent: true,
        }),
      );
      mesh.position.set(e.x, 1.65, e.z);
      this.scene.add(mesh);
      const angle = i * 2.4 + e.id,
        speed = explosion ? 5 : 2.5;
      this.particles.push({
        mesh,
        vx: Math.cos(angle) * speed,
        vz: Math.sin(angle) * speed,
        vy: 1 + (i % 4),
        life: explosion ? 0.95 : 0.4,
        max: explosion ? 0.95 : 0.4,
      });
    }
  }
  loop(now) {
    requestAnimationFrame(this.loop);
    const dt = Math.min((now - this.lastFrame) / 1000, 0.05);
    this.lastFrame = now;
    if (document.hidden) {
      this.started = now;
      this.frames = 0;
      return;
    }
    const rect = this.canvas.getBoundingClientRect();
    if (this.width !== rect.width || this.height !== rect.height) {
      this.width = rect.width;
      this.height = rect.height;
      this.renderer.setSize(rect.width, rect.height, false);
      this.camera.aspect = rect.width / Math.max(1, rect.height);
      this.camera.updateProjectionMatrix();
    }
    this.camera.position.set(
      this.target.x + this.radius * Math.sin(this.phi) * Math.sin(this.theta),
      this.target.y + this.radius * Math.cos(this.phi),
      this.target.z + this.radius * Math.sin(this.phi) * Math.cos(this.theta),
    );
    this.camera.lookAt(this.target);
    if (this.state) {
      const blend = clamp((now - this.updated) / 240, 0, 1),
        s = this.state,
        prev = this.previous;
      for (const [key, data] of [
        ["player", s.player],
        ...s.enemies.map((e) => ["enemy" + e.id, e]),
      ]) {
        const r = this.robots.get(key),
          old =
            key === "player"
              ? prev?.player
              : prev?.enemies.find((e) => "enemy" + e.id === key);
        r.root.position.set(
          T.MathUtils.lerp(old?.x ?? data.x, data.x, blend),
          0,
          T.MathUtils.lerp(old?.z ?? data.z, data.z, blend),
        );
        const yaw = old?.yaw ?? data.yaw,
          diff = Math.atan2(Math.sin(data.yaw - yaw), Math.cos(data.yaw - yaw));
        r.body.rotation.y = yaw + diff * blend;
        const phase =
          (s.time +
            (this.playing ? Math.min((now - this.updated) / 1000, 0.25) : 0)) *
          9;
        r.legs.forEach((leg, i) => {
          leg.rotation.x = data.moving
            ? Math.sin(phase + i * Math.PI) * 0.4
            : 0;
        });
        r.body.position.y = data.moving ? Math.abs(Math.sin(phase)) * 0.04 : 0;
        r.dome.material.opacity = 0.6 + Math.sin(now * 0.003) * 0.05;
        r.hp.quaternion.copy(this.camera.quaternion);
      }
      for (const shot of s.projectiles) {
        const old = prev?.projectiles.find((p) => p.id === shot.id);
        this.bullets
          .get(shot.id)
          .position.set(
            T.MathUtils.lerp(old?.x ?? shot.x, shot.x, blend),
            1.8,
            T.MathUtils.lerp(old?.z ?? shot.z, shot.z, blend),
          );
      }
    }
    for (const p of this.particles) {
      p.life -= dt;
      p.mesh.position.x += p.vx * dt;
      p.mesh.position.z += p.vz * dt;
      p.mesh.position.y += p.vy * dt;
      p.vy -= dt * 7;
      p.mesh.material.opacity = Math.max(0, p.life / p.max);
    }
    this.particles = this.particles.filter((p) => {
      if (p.life > 0) return true;
      this.disposeTree(p.mesh);
      return false;
    });
    this.renderer.render(this.scene, this.camera);
    this.frames++;
    if (now - this.started > 2000) {
      this.report({
        mode: "webgl2",
        fps: (this.frames * 1000) / (now - this.started),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        frames: this.frames,
        quality: this.quality,
      });
      this.frames = 0;
      this.started = now;
    }
  }
}
