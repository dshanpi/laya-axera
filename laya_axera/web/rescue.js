/* Real decisions are fetched from the API. Canvas interpolation never advances the world. */
"use strict";
const $ = (id) => document.getElementById(id);
const labels = {
  rescue: "救援",
  evade: "避险",
  refuel: "补给",
  return: "返航",
};
const modeLabels = {
  laya: "LAYA / NPU",
  rule: "固定规则 / CPU",
  human: "手动驾驶",
};
const endings = {
  docked: "已抵达母港",
  lost: "飞船损毁",
  stranded: "燃料耗尽",
  timeout: "任务超时",
  halted: "任务已停止",
};
let session = null,
  data = null,
  decision = null,
  busy = false,
  running = false,
  timer = null;
let animationStart = 0,
  visualFrom = null,
  animationDuration = 1000;
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const canvas = $("space"),
  ctx = canvas.getContext("2d");
const defaultWorld = {
  ship: { x: 115, y: 320 },
  base: { x: 115, y: 320 },
  pods: [
    { id: 1, x: 380, y: 240 },
    { id: 2, x: 650, y: 360 },
    { id: 3, x: 845, y: 220 },
  ],
  depots: [
    { x: 440, y: 480, stock: 1 },
    { x: 740, y: 150, stock: 1 },
  ],
  trail: [],
  threat: 18,
};
let rngSeed = 711;
const random = () => {
  rngSeed = (1664525 * rngSeed + 1013904223) >>> 0;
  return rngSeed / 4294967296;
};
const stars = Array.from({ length: 190 }, () => ({
  x: random() * 1070,
  y: random() * 640,
  r: random() * 1.3 + 0.25,
  a: random(),
  phase: random() * 7,
}));
const rocks = Array.from({ length: 35 }, () => ({
  x: 220 + random() * 800,
  y: 70 + random() * 530,
  r: 7 + random() * 16,
  speed: 2 + random() * 5,
  phase: random() * 7,
}));
for (const [key, label] of Object.entries(labels)) {
  const row = document.createElement("div");
  row.className = "prob-row";
  row.id = `prob-${key}`;
  const name = document.createElement("span");
  name.textContent = label;
  const track = document.createElement("div");
  track.className = "prob-track";
  const fill = document.createElement("div");
  fill.className = "prob-fill";
  fill.style.width = "0%";
  track.append(fill);
  const value = document.createElement("span");
  value.textContent = "—";
  row.append(name, track, value);
  $("probabilities").append(row);
}
async function api(path, body) {
  const controller = new AbortController(),
    timeout = setTimeout(() => controller.abort(), 90000);
  try {
    const response = await fetch("/api/rescue/" + path, {
      method: body ? "POST" : "GET",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
    const value = await response.json();
    if (!response.ok)
      throw new Error(
        typeof value.detail === "string"
          ? value.detail
          : JSON.stringify(value.detail),
      );
    return value;
  } finally {
    clearTimeout(timeout);
  }
}
function notify(message, error = false) {
  $("notice").textContent = message;
  $("notice").classList.toggle("error", error);
}
function pause() {
  running = false;
  clearTimeout(timer);
  timer = null;
  updateControls();
}
function updateControls() {
  const done = !!data?.done,
    human = (data?.mode || $("mode").value) === "human";
  $("play").textContent = human
    ? session
      ? "手动驾驶中"
      : "建立手动任务"
    : running
      ? "暂停任务"
      : session
        ? "继续任务"
        : "开始任务";
  $("play").disabled = done || (human && !!session) || (busy && !running);
  $("step").disabled = busy || running || done || human;
  $("new").disabled = busy;
  $("storm").disabled = $("leak").disabled = busy || !session || done;
  $("export").disabled = !session || busy;
  $("manual").hidden = !human;
  document
    .querySelectorAll("[data-action]")
    .forEach((b) => (b.disabled = busy || !session || done));
  $("status").textContent = busy
    ? "正在处理"
    : done
      ? endings[data.state.status] || "已结束"
      : running
        ? "任务进行中"
        : session
          ? "已暂停"
          : "待命";
}
function center(title, subtitle) {
  $("center-message").hidden = !title;
  if (title) {
    $("center-message").replaceChildren();
    const b = document.createElement("b"),
      s = document.createElement("span");
    b.textContent = title;
    s.textContent = subtitle;
    $("center-message").append(b, s);
  }
}
function render() {
  if (!data) return;
  const s = data.state;
  $("division").textContent =
    `星图为程序绘制 · ${data.mode === "laya" ? "Laya 决策" : data.mode === "rule" ? "固定规则决策" : "手动指令"}`;
  $("turn").textContent = `回合 ${String(s.turn).padStart(2, "0")} / 30`;
  for (const key of ["fuel", "hull", "threat"]) {
    $(key).replaceChildren(document.createTextNode(String(s[key])));
    const small = document.createElement("small");
    small.textContent = "/ 100";
    $(key).append(small);
    $(`${key}-meter`).value = s[key];
  }
  $("crew").textContent = `${s.rescued} / ${s.delivered}`;
  $("score").textContent = `任务得分 ${s.score}`;
  $("source").textContent = modeLabels[data.mode];
  $("calls").textContent = `NPU 推理 ${data.stats.npu_calls} 次`;
  $("guards").textContent = `保护介入 ${data.stats.interventions} 次`;
  if (decision) {
    $("proposed").textContent = labels[decision.proposed];
    $("executed").textContent = labels[decision.executed] || "停止";
    $("guard-note").textContent =
      decision.reason ||
      (data.mode === "laya"
        ? "按 Laya 的原始选择执行。"
        : data.mode === "rule"
          ? "固定阈值规则选择；未调用模型。"
          : "按手动指令执行；未调用模型。");
    $("guard-note").classList.toggle("intervened", decision.intervened);
    $("risk").textContent =
      decision.risk === null ? "—" : decision.risk.toFixed(2);
    $("emergency").textContent =
      decision.emergency === null
        ? "—"
        : `${(decision.emergency * 100).toFixed(1)}%`;
    $("latency").textContent =
      decision.npu_ms === null ? "—" : `${decision.npu_ms.toFixed(0)} ms`;
    $("raw").textContent = JSON.stringify(
      {
        request: decision.request,
        answers: decision.raw_answers,
        engine: decision.engine,
        token_counts: decision.token_counts,
        proposed: decision.proposed,
        executed: decision.executed,
        guard_reason: decision.reason,
        decision_ms: decision.decision_ms,
      },
      null,
      2,
    );
    if (decision.engine)
      $("engine").textContent =
        `${decision.engine.provider} · device ${decision.engine.device_id}`;
  } else {
    $("proposed").textContent = "等待决策";
    $("executed").textContent = "—";
    $("guard-note").textContent = "尚未执行决策";
    $("guard-note").classList.remove("intervened");
    for (const key of ["risk", "emergency", "latency"])
      $(key).textContent = "—";
    $("raw").textContent = "暂无决策数据";
  }
  for (const key of Object.keys(labels)) {
    const row = $(`prob-${key}`),
      p = decision?.probabilities?.[key];
    row.classList.toggle(
      "selected",
      decision?.proposed === key && p !== undefined,
    );
    row.querySelector(".prob-fill").style.width =
      p === undefined ? "0%" : `${p * 100}%`;
    row.lastElementChild.textContent =
      p === undefined ? "—" : `${(p * 100).toFixed(1)}%`;
  }
  $("log").replaceChildren();
  for (const item of [...data.history].reverse()) {
    const li = document.createElement("li"),
      time = document.createElement("time"),
      text = document.createElement("span");
    time.textContent = `#${String(item.revision).padStart(2, "0")}`;
    const d = item.decision;
    text.textContent =
      item.kind === "event"
        ? item.event === "storm"
          ? "环境变化 · 风暴 +55"
          : "环境变化 · 燃料 −22"
        : `${labels[d.proposed]}${d.intervened ? " → " + (labels[d.executed] || "停止") + " · 保护介入" : ""} · ${d.npu_ms === null ? "无 NPU 调用" : d.npu_ms.toFixed(0) + " ms"}`;
    li.append(time, text);
    $("log").append(li);
  }
  if (!data.history.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "等待第一轮决策";
    $("log").append(li);
  }
  $("flight-caption").textContent = data.done
    ? `${endings[s.status]} · 已送达 ${s.delivered} 人`
    : decision
      ? `${labels[decision.executed] || "停止"} · 已接回 ${s.rescued} 人 / 剩余 ${s.pods.length} 人`
      : "航线已建立，等待指令";
  if (data.done) {
    pause();
    center(
      endings[s.status],
      `已接回 ${s.rescued} 人，安全送达 ${s.delivered} 人，得分 ${s.score}。可用相同种子切换驾驶员重试。`,
    );
  } else center(null);
  updateControls();
}
async function recover(error) {
  pause();
  if (session) {
    try {
      data = await api(session);
      decision =
        [...data.history].reverse().find((x) => x.decision)?.decision || null;
      render();
    } catch {
      /* Preserve the last known state; never retry a decision automatically. */
    }
  }
  notify(`已暂停：${error.message}。请检查服务，确认状态后再继续。`, true);
}
async function createMission() {
  pause();
  busy = true;
  updateControls();
  notify("正在建立任务，首次加载模型可能需要几秒。");
  try {
    const next = await api("new", {
      mode: $("mode").value,
      scenario: $("scenario").value,
      seed: Number($("seed").value),
      mission: $("mission").value,
      guarded: $("guarded").checked,
    });
    session = next.session;
    data = next;
    decision = null;
    visualFrom = null;
    render();
    notify(
      data.mode === "human"
        ? "手动任务已建立。使用救援、避险、补给、返航按钮驾驶飞船。"
        : "任务已建立。可开始连续决策、执行单步，或注入环境变化。",
    );
    return true;
  } catch (e) {
    notify(`建立失败：${e.message}`, true);
    return false;
  } finally {
    busy = false;
    updateControls();
  }
}
async function step(action) {
  if (busy || data?.done) return;
  if (!session && !(await createMission())) return;
  busy = true;
  updateControls();
  notify(
    data.mode === "laya"
      ? "Laya 正在计算行动、风险和返航判断…"
      : "正在执行指令…",
  );
  try {
    const previous = data.state.ship;
    const next = await api("step", {
      session,
      revision: data.revision,
      ...(action ? { action } : {}),
    });
    data = next;
    decision = next.decision;
    visualFrom = previous;
    animationStart = performance.now();
    animationDuration = reducedMotion ? 0 : Number($("speed").value) * 0.8;
    render();
    notify(
      data.done
        ? "本次任务已结束，可导出记录或重建任务。"
        : decision.intervened
          ? decision.reason
          : "决策已执行。画面展示该次行动的飞行轨迹。",
    );
  } catch (e) {
    await recover(e);
  } finally {
    busy = false;
    updateControls();
    if (running && !data?.done)
      timer = setTimeout(() => step(), Number($("speed").value));
  }
}
$("new").addEventListener("click", createMission);
$("play").addEventListener("click", async () => {
  if (running) {
    pause();
    notify(busy ? "将在当前决策完成后暂停。" : "任务已暂停。");
    return;
  }
  if (!session && !(await createMission())) return;
  if (data.mode === "human") return;
  running = true;
  step();
});
$("step").addEventListener("click", () => step());
$("mode").addEventListener("change", () => {
  updateControls();
  notify("驾驶员设置将在重建任务后生效。");
});
for (const event of ["storm", "leak"])
  $(event).addEventListener("click", async () => {
    if (busy || !session || data.done) return;
    const resume = running;
    pause();
    busy = true;
    updateControls();
    try {
      data = await api("event", { session, revision: data.revision, event });
      render();
      notify(
        event === "storm"
          ? "风暴强度增加 55；观察下一轮模型选择。"
          : "燃料减少 22；观察下一轮模型选择。",
      );
      running = resume && !data.done;
    } catch (e) {
      await recover(e);
    } finally {
      busy = false;
      updateControls();
      if (running) timer = setTimeout(() => step(), 400);
    }
  });
document
  .querySelectorAll("[data-action]")
  .forEach((button) =>
    button.addEventListener("click", () => step(button.dataset.action)),
  );
$("export").addEventListener("click", () => {
  if (!data) return;
  const blob = new Blob(
    [
      JSON.stringify(
        {
          format: "laya-rescue-v1",
          exported_at: new Date().toISOString(),
          ...data,
        },
        null,
        2,
      ),
    ],
    { type: "application/json" },
  );
  const url = URL.createObjectURL(blob),
    link = document.createElement("a");
  link.href = url;
  link.download = `laya-rescue-${data.state.seed}-${data.mode}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden && running) {
    pause();
    notify("页面已隐藏，连续决策已暂停。");
  }
});
window.addEventListener("pagehide", pause);
document.addEventListener("keydown", (event) => {
  if (
    event.code === "Space" &&
    !["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(event.target.tagName)
  ) {
    event.preventDefault();
    if (!$("play").disabled) $("play").click();
  }
});

function circle(x, y, r, color, width = 1) {
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.stroke();
}
function textAt(text, x, y, color = "#91a8c5", size = 10) {
  ctx.font = `${size}px "Segoe UI","Microsoft YaHei",sans-serif`;
  ctx.textAlign = "center";
  ctx.fillStyle = color;
  ctx.fillText(text, x, y);
}
function draw(now) {
  const rect = canvas.getBoundingClientRect(),
    dpr = Math.min(devicePixelRatio || 1, 2);
  if (
    canvas.width !== Math.round(rect.width * dpr) ||
    canvas.height !== Math.round(rect.height * dpr)
  ) {
    canvas.width = Math.round(rect.width * dpr);
    canvas.height = Math.round(rect.height * dpr);
  }
  ctx.setTransform(canvas.width / 1070, 0, 0, canvas.height / 640, 0, 0);
  const t = reducedMotion ? 0 : now / 1000,
    s = data?.state || defaultWorld;
  ctx.fillStyle = "#080f1c";
  ctx.fillRect(0, 0, 1070, 640);
  let glow = ctx.createRadialGradient(670, 290, 0, 670, 290, 490);
  glow.addColorStop(0, "#20384a");
  glow.addColorStop(0.5, "#112337");
  glow.addColorStop(1, "#080f1c");
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, 1070, 640);
  glow = ctx.createRadialGradient(300, 500, 0, 300, 500, 450);
  glow.addColorStop(0, "#25404344");
  glow.addColorStop(1, "#10203000");
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, 1070, 640);
  ctx.strokeStyle = "#6682a30d";
  ctx.lineWidth = 1;
  for (let x = -640; x < 1250; x += 85) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x + 500, 640);
    ctx.stroke();
  }
  for (let y = 30; y < 640; y += 65) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(1070, y);
    ctx.stroke();
  }
  for (const star of stars) {
    ctx.globalAlpha =
      0.3 + star.a * 0.45 + Math.sin(t * 0.7 + star.phase) * 0.12;
    ctx.fillStyle = "#c3dbee";
    ctx.beginPath();
    ctx.arc(star.x, star.y, star.r, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
  // Distant planet, orbital rings and sector annotation are decorative.
  const planet = ctx.createRadialGradient(982, 190, 6, 985, 235, 137);
  planet.addColorStop(0, "#51687c");
  planet.addColorStop(0.45, "#263d50");
  planet.addColorStop(1, "#0a1421");
  ctx.fillStyle = planet;
  ctx.beginPath();
  ctx.arc(1012, 220, 127, 0, Math.PI * 2);
  ctx.fill();
  circle(1012, 220, 134, "#9abbd51c");
  ctx.save();
  ctx.translate(1012, 220);
  ctx.rotate(-0.35);
  ctx.scale(1, 0.33);
  circle(0, 0, 185, "#96b9d229", 2);
  circle(0, 0, 190, "#a7c7e014");
  ctx.restore();
  const count = Math.floor(3 + s.threat * 0.3);
  for (const rock of rocks.slice(0, count)) {
    const x = rock.x + Math.sin(t * 0.16 + rock.phase) * 16,
      y = rock.y + Math.cos(t * 0.1 + rock.phase) * 9;
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(rock.phase + t * 0.035);
    ctx.beginPath();
    for (let i = 0; i < 7; i++) {
      const a = (i * Math.PI * 2) / 7,
        r = rock.r * (0.8 + 0.15 * Math.sin(i * 5 + rock.phase));
      const px = Math.cos(a) * r,
        py = Math.sin(a) * r;
      i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
    }
    ctx.closePath();
    ctx.fillStyle = s.threat > 55 ? "#77535c77" : "#45566966";
    ctx.fill();
    ctx.strokeStyle = s.threat > 55 ? "#e1948255" : "#8ca2b52a";
    ctx.stroke();
    ctx.restore();
  }
  ctx.setLineDash([3, 9]);
  circle(s.base.x, s.base.y, 155, "#78bbc11a");
  circle(s.base.x, s.base.y, 270, "#78bbc112");
  ctx.setLineDash([]);
  ctx.save();
  ctx.translate(s.base.x, s.base.y);
  ctx.rotate(t * 0.035);
  circle(0, 0, 29, "#8dd0d085", 3);
  circle(0, 0, 39, "#75a9bd40");
  for (let i = 0; i < 4; i++) {
    ctx.rotate(Math.PI / 2);
    ctx.fillStyle = "#83adbc";
    ctx.fillRect(-9, 25, 18, 8);
  }
  ctx.restore();
  textAt("母港 · HOME", s.base.x, s.base.y + 63, "#aac7d7", 11);
  for (const d of s.depots) {
    ctx.save();
    ctx.translate(d.x, d.y);
    ctx.globalAlpha = d.stock ? 1 : 0.25;
    ctx.strokeStyle = "#edc17a";
    ctx.fillStyle = "#554931";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(0, -16);
    ctx.lineTo(15, 0);
    ctx.lineTo(0, 16);
    ctx.lineTo(-15, 0);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "#ffe1a0";
    ctx.fillRect(-4, -4, 8, 8);
    circle(0, 0, 25, "#eec47925");
    textAt(d.stock ? "补给 +38" : "补给已用尽", 0, 39, "#cbb381", 10);
    ctx.restore();
  }
  for (const p of s.pods) {
    ctx.save();
    ctx.translate(p.x, p.y);
    circle(0, 0, 16 + Math.sin(t * 2 + p.id) * 3, "#71e2d035");
    circle(0, 0, 24, "#71e2d010");
    ctx.shadowColor = "#71e2d0";
    ctx.shadowBlur = 15;
    ctx.fillStyle = "#81edd6";
    ctx.fillRect(-4, -7, 8, 14);
    ctx.shadowBlur = 0;
    ctx.strokeStyle = "#c5fff1";
    ctx.strokeRect(-6, -9, 12, 18);
    textAt(`SOS ${String(p.id).padStart(2, "0")}`, 0, 35, "#7dc9bd", 9);
    ctx.restore();
  }
  if (s.trail.length > 1) {
    ctx.strokeStyle = "#71e2d038";
    ctx.lineWidth = 2;
    ctx.setLineDash([4, 6]);
    ctx.beginPath();
    s.trail.forEach((p, i) =>
      i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y),
    );
    ctx.stroke();
    ctx.setLineDash([]);
  }
  const progress = animationDuration
      ? Math.min(1, (now - animationStart) / animationDuration)
      : 1,
    ease = progress * progress * (3 - 2 * progress),
    from = visualFrom || s.ship;
  const x = from.x + (s.ship.x - from.x) * ease,
    y = from.y + (s.ship.y - from.y) * ease,
    angle = Math.atan2(s.ship.y - from.y, s.ship.x - from.x);
  if (progress < 1) {
    ctx.strokeStyle = "#8df3d866";
    ctx.setLineDash([5, 8]);
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(s.ship.x, s.ship.y);
    ctx.stroke();
    ctx.setLineDash([]);
    circle(s.ship.x, s.ship.y, 22, "#7ce1ca50");
  }
  if (
    s.last_action?.action === "rescue" &&
    progress > 0.7 &&
    now - animationStart < 2200
  ) {
    ctx.save();
    ctx.globalAlpha = Math.max(0, 1 - (now - animationStart) / 2200);
    circle(s.ship.x, s.ship.y, 30 + (now - animationStart) / 45, "#85ffe4", 2);
    ctx.fillStyle = "#72ffd728";
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x - 20, y + 65);
    ctx.lineTo(x + 20, y + 65);
    ctx.fill();
    ctx.restore();
  }
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(angle);
  ctx.shadowColor = "#6df4d5";
  ctx.shadowBlur = 25;
  if (progress < 1) {
    const flame = 23 + Math.sin(t * 45) * 7;
    ctx.fillStyle = "#76e7e2";
    ctx.beginPath();
    ctx.moveTo(-14, -5);
    ctx.lineTo(-flame - 12, 0);
    ctx.lineTo(-14, 5);
    ctx.fill();
  }
  ctx.shadowBlur = 0;
  ctx.fillStyle = "#d4e4ed";
  ctx.strokeStyle = "#6ba8b8";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(22, 0);
  ctx.lineTo(-16, -14);
  ctx.lineTo(-9, 0);
  ctx.lineTo(-16, 14);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "#73dddf";
  ctx.beginPath();
  ctx.moveTo(11, 0);
  ctx.lineTo(-5, -4);
  ctx.lineTo(-5, 4);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
  if (s.last_action?.action === "evade") {
    circle(x, y, 35 + Math.sin(t * 3) * 2, "#79dff17a", 2);
    circle(x, y, 40, "#79dff122");
  }
  textAt("RESCUE · 01", x, y - 32, "#dcebf3", 9);
  requestAnimationFrame(draw);
}
updateControls();
requestAnimationFrame(draw);
fetch("/api/info")
  .then((r) => {
    if (!r.ok) throw Error("服务不可用");
    return r.json();
  })
  .then((info) => {
    const ready = info.models.find((m) => m.status === "ready");
    $("engine").textContent = ready
      ? `${ready.provider} · device ${ready.device_id}`
      : "AXERA 服务已连接 · 模型按需加载";
  })
  .catch((error) => {
    $("engine").textContent = "服务未连接";
    notify(error.message, true);
  });
