import { ArenaRenderer } from "./mech-scene.js";

const $ = (id) => document.getElementById(id);
const labels = {
  attack: "进攻",
  defend: "防御",
  retreat: "撤退",
  hold: "待命",
};
const descriptions = {
  attack: "寻找射击位置 · 自动瞄准开火",
  defend: "展开能量护盾 · 拦截来袭弹道",
  retreat: "导航到掩体后 · 脱离敌方视线",
  hold: "保持位置 · 停止移动和开火",
};
const icons = { attack: "⌖", defend: "⬡", retreat: "↙", hold: "Ⅱ" };
let session,
  data,
  pending = 0,
  ticking = false,
  blocked = false,
  sequence = Promise.resolve(),
  audio,
  audioEnabled = false,
  qualityChosen = false,
  slowSamples = 0,
  lastReport = 0;

for (const action of Object.keys(labels)) {
  const row = document.createElement("div");
  row.className = "prob-row";
  row.dataset.action = action;
  row.innerHTML = `<span>${labels[action]}</span><div class="prob-track"><i id="bar-${action}"></i></div><span id="prob-${action}">—</span>`;
  $("prob-list").append(row);
}

function sound(kind) {
  if (!audioEnabled || !audio || audio.state !== "running") return;
  const osc = audio.createOscillator(),
    gain = audio.createGain();
  osc.connect(gain);
  gain.connect(audio.destination);
  osc.type = kind === "shield" ? "sine" : "triangle";
  const t = audio.currentTime;
  osc.frequency.setValueAtTime(
    kind === "shield" ? 760 : kind === "explosion" ? 95 : 250,
    t,
  );
  osc.frequency.exponentialRampToValueAtTime(45, t + 0.12);
  gain.gain.setValueAtTime(0.035, t);
  gain.gain.exponentialRampToValueAtTime(0.001, t + 0.15);
  osc.start(t);
  osc.stop(t + 0.16);
}
const renderer = new ArenaRenderer(
  $("arena"),
  (report) => {
    $("graphics").textContent =
      report.mode === "lost"
        ? "图形上下文已丢失，请刷新页面"
        : `${report.mode === "webgl2" ? "WebGL 2 · 3D" : "2D 兼容模式"} · ${Math.round(report.fps)} FPS`;
    if (report.mode === "lost") {
      blocked = true;
      pause(false);
    }
    if (
      !qualityChosen &&
      report.mode === "webgl2" &&
      report.quality === "balanced"
    ) {
      slowSamples = report.fps < 24 ? slowSamples + 1 : 0;
      if (slowSamples >= 3) {
        renderer.setQuality("low");
        $("quality").value = "low";
        $("graphics").title =
          "检测到连续低帧率，已自动切换流畅画质。可手动重新选择。";
      }
    }
    if (session && performance.now() - lastReport > 10000) {
      lastReport = performance.now();
      fetch("/api/mech/graphics", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session, ...report }),
      }).catch(() => {});
    }
  },
  sound,
);

async function request(path, body) {
  const r = await fetch(
    "/api/mech" + path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  let result;
  try {
    result = await r.json();
  } catch {
    throw new Error(`服务响应异常 (${r.status})`);
  }
  if (!r.ok)
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : `请求被拒绝 (${r.status})`,
    );
  return result;
}
function notice(text, error = false) {
  $("notice").textContent = text;
  $("notice").classList.toggle("error", error);
}
function paint() {
  if (!data) return;
  const s = data.state,
    d = data.decision,
    playing = data.playing && !blocked;
  $("armor").textContent = Math.ceil(s.player.armor);
  $("energy").textContent = Math.floor(s.player.energy);
  $("armor-bar").style.width = s.player.armor + "%";
  $("energy-bar").style.width = s.player.energy + "%";
  $("kills").textContent = `击败 ${s.stats.kills} / ${s.enemies.length}`;
  $("blocked").textContent = `护盾拦截 ${s.stats.blocked}`;
  $("time").textContent =
    `${String(Math.floor(s.time / 60)).padStart(2, "0")}:${String(Math.floor(s.time % 60)).padStart(2, "0")}`;
  $("stage-state").textContent =
    s.status !== "active"
      ? { won: "训练完成", lost: "装甲耗尽", timeout: "训练结束" }[s.status]
      : playing
        ? "训练进行中"
        : s.time
          ? "训练已暂停"
          : "准备训练";
  $("pause").textContent = playing ? "Ⅱ 暂停训练" : "▶ 继续训练";
  $("pause").disabled = !session || s.status !== "active";
  $("motion").textContent = `${labels[s.action]} · ${descriptions[s.action]}`;
  $("center").hidden = playing;
  $("center").classList.toggle("compact", !!d && s.status === "active");
  if (!playing) {
    const done = s.status !== "active";
    $("center").querySelector(".kicker").textContent = done
      ? "SESSION COMPLETE"
      : d
        ? "SIMULATION PAUSED"
        : "SYSTEM ONLINE";
    $("center").querySelector("h2").textContent = done
      ? s.status === "won"
        ? "训练目标已击败"
        : s.status === "lost"
          ? "装甲耗尽，重新挑战"
          : "本轮训练结束"
      : d
        ? "训练已暂停"
        : "等待你的第一条指令";
    $("center").querySelector("p").textContent = done
      ? `射击 ${s.stats.shots} 次 · 命中 ${s.stats.hits} 次 · 护盾拦截 ${s.stats.blocked} 次`
      : d
        ? "继续训练，或发送新的操控指令。"
        : "试试“别开火，先保护自己。”";
  }
  $("source").textContent =
    d?.source === "laya" ? "LAYA 推理" : d ? "手动操作" : "等待指令";
  $("last-command").textContent =
    d?.command || (d ? "手动选择：" + labels[d.action] : "尚未发送");
  for (const action of Object.keys(labels)) {
    const p = d?.probabilities?.[action];
    $("prob-" + action).textContent =
      p == null ? "—" : (p * 100).toFixed(1) + "%";
    $("bar-" + action).style.width = p == null ? "0%" : p * 100 + "%";
    document
      .querySelector(`[data-action="${action}"]`)
      .classList.toggle("selected", d?.action === action);
  }
  $("action").textContent = d ? `${labels[d.action]}模式` : "等待指令";
  $("action-icon").textContent = icons[d?.action] || "◇";
  $("latency").textContent =
    d?.npu_ms != null ? `${d.npu_ms.toFixed(1)} ms` : "—";
  $("model").textContent = d?.model || (d ? "未调用模型" : "尚未推理");
  if (d?.engine?.provider) $("engine").textContent = d.engine.provider;
  $("inference-count").textContent = `NPU 调用 ${data.npu_calls} 次`;
  $("distribution").textContent = d?.probabilities ? "四选一 · 原始概率" : "—";
  $("raw").textContent = d ? JSON.stringify(d, null, 2) : "尚无模型输出";
  const history = $("history");
  history.replaceChildren();
  for (const item of [...data.history].reverse().slice(0, 5)) {
    const li = document.createElement("li");
    const time = document.createElement("time");
    time.textContent = `${item.time.toFixed(1)}s`;
    const span = document.createElement("span");
    span.textContent =
      item.kind === "command"
        ? `${item.decision.source === "manual" ? "手动" : "Laya"} → ${labels[item.decision.action]}`
        : `现场干预：${{ enemy: "增加敌人", armor: "降低装甲", cover: "生成掩体" }[item.event]}`;
    li.append(time, span);
    history.append(li);
  }
  if (!history.children.length) {
    const li = document.createElement("li");
    li.textContent = "等待第一条指令";
    history.append(li);
  }
  renderer.update(s, playing);
  busy();
}
function busy() {
  const unavailable = !session || data?.state.status !== "active";
  $("send").disabled = pending > 0 || unavailable;
  $("send").textContent = pending ? "处理中…" : "发送指令 ↗";
  $("input-state").textContent = pending ? "等待真实结果" : "ENTER ↵";
  document
    .querySelectorAll("[data-command],[data-event],[data-manual]")
    .forEach((b) => {
      b.disabled = pending > 0 || unavailable;
    });
}
function enqueue(work) {
  pending++;
  busy();
  const result = sequence.then(work);
  sequence = result
    .catch(async (error) => {
      blocked = true;
      notice(error.message + "；训练已暂停，未切换为规则控制。", true);
      if (session) {
        try {
          data = await request("/" + session);
          data = await request("/pause", {
            session,
            revision: data.revision,
            playing: false,
          });
        } catch {}
      }
      paint();
    })
    .finally(() => {
      pending--;
      busy();
    });
  return sequence;
}
function mutate(path, extra = {}) {
  return request(path, { session, revision: data.revision, ...extra });
}
function send(text) {
  if (!text.trim() || pending) return;
  $("command").value = text;
  notice("Laya 正在识别操控意图，首次加载模型可能需要数秒…");
  enqueue(async () => {
    data = await mutate("/command", { text });
    blocked = false;
    paint();
    notice(
      `Laya 选择“${labels[data.decision.action]}”。${descriptions[data.decision.action]}。`,
    );
  });
}
function pause(playing) {
  if (!session) return Promise.resolve();
  if (!playing) blocked = true;
  return enqueue(async () => {
    data = await mutate("/pause", { playing });
    blocked = !playing;
    paint();
    notice(playing ? "训练已继续。" : "训练已暂停。暂停操作不依赖模型判断。");
  });
}
async function reset() {
  blocked = true;
  await enqueue(async () => {
    const result = await request("/new", {
      seed: 42,
      difficulty: $("difficulty").value,
    });
    session = result.session;
    data = result;
    renderer.reset?.();
    blocked = false;
    paint();
    notice("训练场已就绪。输入一句话，让 Laya 选择动作。");
  });
}

$("command-form").addEventListener("submit", (e) => {
  e.preventDefault();
  send($("command").value);
});
document
  .querySelectorAll("[data-command]")
  .forEach((b) => b.addEventListener("click", () => send(b.dataset.command)));
document.querySelectorAll("[data-event]").forEach((b) =>
  b.addEventListener("click", () =>
    enqueue(async () => {
      data = await mutate("/event", { event: b.dataset.event });
      paint();
      notice("战况已更新。可以发送下一条指令。");
    }),
  ),
);
document.querySelectorAll("[data-manual]").forEach((b) =>
  b.addEventListener("click", () =>
    enqueue(async () => {
      data = await mutate("/manual", { action: b.dataset.manual });
      blocked = false;
      paint();
      notice("手动操作：未调用 Laya，概率与推理耗时已清空。");
    }),
  ),
);
$("pause").addEventListener("click", () => pause(!(data?.playing && !blocked)));
$("reset").addEventListener("click", reset);
$("camera").addEventListener("click", () => renderer.toggleCamera());
$("quality").addEventListener("change", () => {
  qualityChosen = true;
  renderer.setQuality($("quality").value);
});
$("sound").addEventListener("click", async () => {
  try {
    audio ||= new (window.AudioContext || window.webkitAudioContext)();
    await audio.resume();
    audioEnabled = !audioEnabled;
    $("sound").textContent = `音效：${audioEnabled ? "开" : "关"}`;
    $("sound").setAttribute("aria-pressed", String(audioEnabled));
  } catch {
    notice("当前浏览器无法启用音效。", true);
  }
});
$("export").addEventListener("click", () => {
  if (!data) return;
  const blob = new Blob(
    [
      JSON.stringify(
        { exported_at: new Date().toISOString(), session, ...data },
        null,
        2,
      ),
    ],
    { type: "application/json" },
  );
  const url = URL.createObjectURL(blob),
    a = document.createElement("a");
  a.href = url;
  a.download = "laya-mech-session.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
document.addEventListener("keydown", (e) => {
  if (
    e.code === "Space" &&
    !["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(e.target.tagName) &&
    !e.repeat
  ) {
    e.preventDefault();
    pause(!(data?.playing && !blocked));
  }
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden && data?.playing) pause(false);
});
// Fixed simulation steps, at most one network mutation in flight. Slow clients slow the
// simulation instead of catching up with unbounded hidden ticks or stale commands.
setInterval(() => {
  if (
    !session ||
    pending ||
    ticking ||
    blocked ||
    !data?.playing ||
    document.hidden
  )
    return;
  ticking = true;
  sequence = sequence
    .then(async () => {
      data = await mutate("/tick", { dt: 0.25 });
      paint();
    })
    .catch((error) => {
      blocked = true;
      notice(`连接中断，训练已暂停：${error.message}`, true);
      paint();
    })
    .finally(() => {
      ticking = false;
    });
}, 250);
fetch("/api/info")
  .then((r) => r.json())
  .then((info) => {
    $("engine").textContent =
      info.models?.find((m) => m.name === info.default_model)?.provider ||
      "本机模型服务";
  })
  .catch(() => {
    $("engine").textContent = "等待模型服务";
  });
reset();
