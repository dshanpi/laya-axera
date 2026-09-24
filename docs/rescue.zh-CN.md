# 部署星际救援指挥官

在 RK3576 主机连接 AX8850 M.2 算力卡，运行 Laya multilingual 模型。浏览器展示救援飞船、逃生舱、补给站和航迹，模型每轮选择救援、避险、补给或返航。

## 准备运行环境

已实测环境：RK3576、AX8850 **16GB** 算力卡、AXCL `V3.16.0_20260729180218`、Python 3.12、PyAXEngine `0.1.3`。本章结果不代表其他容量或固件组合的实测结论。

在连接算力卡的 Linux 主机执行：

```bash
/usr/bin/axcl/axcl-smi
```

确认设备列表中有可用算力卡。安装与 AXCL 环境匹配的 [PyAXEngine wheel](https://github.com/AXERA-TECH/pyaxengine/releases)。下面的 `AXENGINE_WHEEL` 替换为下载文件的绝对路径。

```bash
git clone https://github.com/dshanpi/laya-axera.git
cd laya-axera
python3 -m venv .venv
source .venv/bin/activate
AXENGINE_WHEEL=/path/to/axengine.whl
python -m pip install "$AXENGINE_WHEEL"
python -m pip install '.[web]' huggingface_hub
```

成功标志：`laya-axera --version` 输出版本号。已有项目更新代码后，也要重新执行 `python -m pip install '.[web]'`，使运行环境包含新的页面和接口。

## 下载模型

只需 multilingual checkpoint。以下命令固定到本次验证使用的模型版本：

```bash
hf download AXERA-TECH/Laya \
  --revision 4f02f411fb9b9b09b4a4842b4486177b9594ba9e \
  --include 'multilingual/*' \
  --local-dir models/Laya
```

模型来自 [AXERA-TECH/Laya](https://huggingface.co/AXERA-TECH/Laya)。确认目录中包含 `multilingual/config.json`、`multilingual/model.axmodel` 和 `multilingual/tokenizer/`。

需要代理时，在下载终端设置 `http_proxy`、`https_proxy`，值填写可访问的代理地址。模型已下载时可直接复用，通过 `--model` 指定现有路径。

## 启动游戏

在 Linux 主机的项目目录中执行：

```bash
source .venv/bin/activate
laya-axera serve \
  --model multilingual=models/Laya/multilingual \
  --provider AXCLRTExecutionProvider \
  --device 0 --host 127.0.0.1 --port 8010
```

在该主机的桌面浏览器打开 [星际救援指挥官](http://127.0.0.1:8010/rescue.html)，或从游戏大厅点击“星际救援”。首次建立 Laya 任务时会加载模型，后续任务复用模型实例。

从其他电脑查看时，在其他电脑执行 SSH 转发，将 `<user>` 和 `<board-ip>` 替换为开发板的登录用户和 IP：

```bash
ssh -N -L 8010:127.0.0.1:8010 <user>@<board-ip>
```

然后在该电脑打开同一网址。

Linux 桌面也可使用启动脚本，按需启动服务并打开浏览器：

```bash
bash deploy/launch-rescue.sh
```

使用其他虚拟环境或模型目录时，先设置：

```bash
export LAYA_PYTHON_ENV=/absolute/path/to/venv
export LAYA_MODEL_DIR=/absolute/path/to/Laya
bash deploy/launch-rescue.sh
```

脚本不会设置开机自启。关闭按需启动的后台服务：

```bash
systemctl --user stop laya-games
```

## 观察部署效果

![RK3576 与 AX8850 16GB 上的真实 Laya 决策界面](rescue-desktop.png)

1. 保持“Laya · 算力卡”“常规救援”和地图种子 `42`，点击“单步决策”。查看飞船移动、原始选择、实际执行动作和四项概率。
2. 点击“继续任务”连续运行。每轮调用模型三次，分别回答行动选择、风险评分和是否立即返航；界面中的 NPU 耗时是三次前向计算的合计，不包含网络传输和动画时间。
3. 点击“陨石风暴”增加星区风暴强度，或点击“燃料泄漏”减少燃料。观察下一轮输出和行动变化。
4. 修改“一句话任务”，点击“重建任务”使设置生效。文字过长导致模型输入超过 256 tokens 时会提示缩短，不会静默截断任务。
5. 切换“固定规则 · 对照”或“手动驾驶”，用相同地图种子和场景重建任务。比较已送达人数、行动序列和保护介入次数。规则与手动模式不产生模型概率，也不调用 NPU。
6. 展开“查看本轮输入与输出”检查实际请求和原始输出，点击“导出 JSON”保存完整任务记录。

“暂停任务”会等待正在执行的请求结束，再停止下一轮。切换到其他浏览器标签页也会暂停连续决策。

### 查看实测结果

2026-09-24，使用上面的硬件和模型版本，完成 **23 组任务**：13 组 Laya、9 组固定规则、1 组手动任务。Laya 共执行 **25 轮决策、75 次 NPU 前向计算**，每轮三次前向计算的总耗时平均 **103.294 ms**，范围 **98.681–127.492 ms**。

默认任务文字为“优先救人，保留返航燃料。”。结果按实际完成情况记录：

| 场景 | 模式 | 地图种子 | 已送达人数 | 观察结果 |
|---|---|---|---|---|
| 常规救援 | Laya，开启保护 | 42、2026、8850 | 各 2 人 | 均执行救援、救援、返航，3 轮完成 |
| 强风暴 | Laya，开启保护 | 42、2026、8850 | 各 0 人 | 第一轮即选择返航 |
| 低燃料 | Laya，开启保护 | 42、2026、8850 | 各 0 人 | 第一轮即选择返航 |
| 常规、强风暴、低燃料 | 固定规则 | 42、2026、8850 | 各 6 人 | 9 组任务均完成全部人员送达 |
| 常规救援，先后注入风暴、燃料泄漏 | Laya，开启保护 | 42 | 4 人 | 4 次救援后返航，共 5 轮 |
| 常规、强风暴、低燃料 | Laya，关闭保护 | 42 | 2、0、0 人 | 与对应保护开启任务的行动序列一致 |
| 常规救援，先后注入风暴、燃料泄漏 | 手动 | 42 | 1 人 | 手动执行救援、避险、返航 |

这 23 组任务未触发保护介入。模型在强风暴、低燃料场景中偏向提前返航，常规场景也未救回全部人员；本次对照中固定规则的送达人数更多。结果说明部署与交互流程可运行，不代表模型已具备可靠的救援规划能力或经过长期稳定性验证。

可下载 [实测结果摘要](rescue-results.json)。在自己的服务上重复同一组测试：

```bash
python examples/rescue_bench.py \
  --url http://127.0.0.1:8010 \
  --output artifacts/rescue.json
```

测试会逐组建立任务并运行到结束，保存实际输入、原始输出、行动和环境变化。执行时先暂停网页里的连续决策。

## 理解决策与保护

Laya 接收当前燃料、船体、风暴、待救人数、已接回人数、任务文字以及各动作的燃料和损伤成本。提示词不包含程序算出的“最佳动作”。模型输出为四项动作概率、0–2 风险期望分和立即返航概率，不生成解释文本。

程序负责最近目标导航、消耗结算和动画。每次救援接回一人，补给站各可使用一次并补充 38 燃料；避险消耗 4 燃料并使风暴降低最多 40。风暴是整个星区的危险强度，画面中的陨石用于表现这一强度。返回母港后每安全送达一人得 150 分；在途人员未送达不计分。任务最多运行 30 回合。

开启保护后，只排除不可执行、会损毁飞船或无法保留返航燃料的动作。如果原始选择被排除，会从允许动作中选取模型概率最高的一项，保留原始概率和选择，并记录介入原因。没有符合条件的动作时停止任务。推理失败时暂停且不推进游戏，不会自动切换成规则驾驶。

三项判断独立计算，因此行动选择、风险评分和立即返航概率可能不一致。飞船按行动选择执行；风险评分与返航概率供观察，不参与保护规则。

概率和风险评分是模型输出，未经过任务成功率校准。修改提示词、任务文字或 checkpoint 可能改变结果；需要按实际业务重新评估。

## 检查运行问题

- **页面打不开**：确认服务进程已启动，端口为 `8010`；远程访问时确认 SSH 转发仍在运行。
- **页面提示模型加载失败**：核对 `--model` 指向 checkpoint 目录，目录内有 `config.json` 和 `model.axmodel`，且 AXCL 能识别设备。
- **更新后看不到入口**：重新安装项目，停止旧服务后再启动，并刷新浏览器。
- **任务提示已过期**：点击“重建任务”。服务重启会清空任务，最多保留 16 个救援会话。
- **需要核对模型是否参与**：选择 Laya 模式，检查输出中的 `engine.provider`、`raw_answers` 和逐轮 `npu_ms`。规则和手动模式的对应字段为空。
