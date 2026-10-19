# 远端 Server Agent 配置指南

目标：先让本地 Windows 通过 SSH 使用 Linux GPU 的图形能力；只在需要远程串流时增加桌面、音频、Sunshine 和完整游戏。文中的目录和 GPU 地址是示例，不是原部署的真实参数。

## 0. 盘点与两端约定

```sh
id
uname -a
nvidia-smi --query-gpu=index,name,pci.bus_id,uuid,memory.total,memory.used,utilization.gpu --format=csv
ulimit -Sn
ulimit -Hn
```

把 GPU 的 index、PCI bus、UUID 和占用者对应起来；获取用户允许使用哪一块 GPU 的确认。敏感枚举结果仅保留私有笔记。不要停止未知 python、Xorg、容器或其他用户的 GPU 任务。使用普通用户拥有的项目目录，不默认更新全局驱动、重启服务器或改变维持当前连接的 VPN。

私有工作目录约定：

```sh
gpuipRoot="$HOME/gpu-over-ip"
mkdir -p "$gpuipRoot/juice-server" "$gpuipRoot/private" "$gpuipRoot/logs"
chmod 700 "$gpuipRoot/private"
```

和 client 约定同一版本、服务端回环端口 43210、客户端隧道端口 14321，以及目标 PCI bus。不要把这些私有配置覆盖进公共仓库示例。

## A. Juice GPU-over-IP：最小服务端

### A1. 驱动与依赖先检查

验证已有 NVIDIA 驱动、Vulkan loader 和对应图形库是否可用。对已下载包用 `ldd ./agent` 和对实际 renderer 的 `ldd` 查缺失项。根据该固定版本实际依赖补齐库；不要把当前商业文档的最新驱动要求直接套到旧社区包。

如必须安装系统软件，明确受影响范围后再由有权限的管理员处理；共享服务器优先使用现有库或专用用户态目录。不要为获得桌面强行升级整台机器驱动。Juice 图形 agent 与 Moonlight 桌面是不同组成部分，前者不要求先安装整个 Steam/Proton 桌面栈。

### A2. 下载同版本官方包

固定历史社区 release：`2023.08.10-2103.0633b794`。从[官方页面](https://github.com/Juice-Labs/Juice-Labs/releases/tag/2023.08.10-2103.0633b794)取得 `JuiceServer-linux.tar.gz`。先检查归档路径，再解压到专用目录：

```sh
gpuipRoot="$HOME/gpu-over-ip"
tar -tzf "$gpuipRoot/JuiceServer-linux.tar.gz"
tar -xzf "$gpuipRoot/JuiceServer-linux.tar.gz" -C "$gpuipRoot/juice-server"
find "$gpuipRoot/juice-server" -maxdepth 3 -type f -name agent
sha256sum "$gpuipRoot/JuiceServer-linux.tar.gz"
```

以实际解压布局定位 agent 和随包资源，不假定 tar 永远没有外层目录。校验来源、版本及上游可用摘要；自己的哈希用于后续一致性记录。本仓库不分发第三方二进制。当前商业版的组织/许可要求按该产品正常处理，不能修改验证来跳过。

### A3. 在 agent 启动前提高文件描述符限制

`ulimit -Sn 65536` 必须在创建 agent 的父进程中生效。对已运行 renderer 改另一个 SSH shell 的限制没有效果。若硬上限低于目标，记录此约束，不假装已经修好。

下面在已经确认有 `./agent` 的目录中运行，SSH 窗口保持打开：

```sh
gpuipRoot="$HOME/gpu-over-ip"
cd "$gpuipRoot/juice-server"
ulimit -Sn 65536 && ./agent --address 127.0.0.1:43210 --disable-gpu-metrics --log-file "$gpuipRoot/logs/juice-agent.log"
```

如果包有外层目录，先进入正确位置。端口已占用时核对进程归属，不杀未知服务；自己的旧实例先正常停止再重启。默认只监听回环，由 client 的 SSH 隧道接入。

如要后台运行，可为专用用户配置进程管理器或限定到该目录的 PID 管理，但必须记录 PID、检查 UID/可执行路径和就绪状态；不要用 `pkill agent` 代替归属验证。

### A4. 与 client 一起验收

另开 SSH 会话检查：

```sh
ss -lntp '( sport = :43210 )'
nvidia-smi
```

client 启动 vkcube 后，检查新 renderer PID 的归属、可执行文件、GPU 和限制：

```sh
# 把实际数字替换进来；不要把占位符原样执行。
cat /proc/实际RendererPID/limits
readlink /proc/实际RendererPID/exe
```

原实践曾遇到软上限 1024 耗尽，使一次小额分配失败并崩溃；启动 agent 前提高限制后，该失败消失。这个修复解释启动崩溃，不等于解决所有低 FPS。必须在实际子进程确认继承，而不是只展示当前 SSH 的 ulimit。

把“agent 就绪、版本一致、GPU 已核对、样例 renderer 已出现/退出”交给 client agent。IP、用户名、UUID、日志内容不要放入公开 issue。

## B. 可选：Sunshine + Moonlight 远端游戏栈

这条路线会在服务器执行完整游戏，需要远端安装或传输游戏主体。只有用户接受该条件时才继续；它不属于本地游戏程序的图形 API 转发。

### B1. 建立专用图形会话

1. 根据本机驱动选择兼容的 Sunshine 和编码器版本。先测试 NVENC，不能把能启动 CPU 编码当成硬件编码成功。
2. 分配一个未占用的 X display，示例 `:93`。保存专用 Xauthority，Xorg 只绑定获准使用的 PCI GPU。GPU 的 Xorg BusID 使用十进制表示，与 `nvidia-smi` 的十六进制 bus 值换算后核对。
3. 验证独立桌面实际使用 NVIDIA：`glxinfo -B`、`xrandr --query`；示例目标 1920×1080@60。不要复用别人的 X/VNC 会话。
4. 启动一个专用 Openbox 等窗口管理器，再启动 Steam，避免窗口焦点和弹窗无法切换。
5. 只有确认自己拥有的显示会话时才执行后续输入；用户的登录、安全和隐私提示交由用户处理。

Xorg 最小示例在 `examples/xorg-headless.conf`，**必须改正确 BusID、Virtual 分辨率，并按系统的 rootless Xorg/seat 权限调整**。不是所有系统都能用同一条免 root 命令启动。

```sh
# 会话变量只作用于当前专用 shell，不写进全局 profile。
export DISPLAY=:93
export XAUTHORITY="$HOME/gpu-over-ip/private/Xauthority"
```

### B2. 独立音频、Sunshine 与无头配对

用独立 PulseAudio 实例和 Unix socket 创建虚拟 sink，不接管系统默认音频。Sunshine 指向专用 DISPLAY、XAUTHORITY、音频 socket 与配置目录；完成编码器探测、实际短录像和音频回环验证。

启动顺序：**显示 → 私有音频 / D-Bus → Sunshine → 窗口管理器 / Steam**。保存仅属于本项目的进程记录，启动前先验证已存在的实例，避免重复占用端口。原有会话就绪时直接复用。

若使用 client 侧“一键远程 Steam”，server agent 要在私有串流部署目录建立 `scripts/start-session.sh`。约定该目录的 Steam 本体为 `runtime/steam-client/ubuntu12_32/steam`，Sunshine 信息端口默认 47989，日志在 `logs/`。此脚本须逐项检查并复用自己的 display/audio/Sunshine/Steam；首次创建后台进程要脱离 SSH 会话并将输出写入私有日志。返回 0 表示准备请求成功。它只准备 Steam，不调用游戏 AppID，不自动启动游戏。将该目录填入 client 私有 JSON 的 `remote_root`；这些部署脚本由 server agent 根据实际机器准备，仓库没有声称已为读者机器安装好。

Sunshine 的证书、配对设备、UUID 和管理员状态必须私有且在重启后保留；不把配对状态重置为空模板。用户可在本地建立管理隧道：

```sh
# 这是 client 机器执行的 SSH 命令，不是在远端再连接自己。
ssh -N -L 127.0.0.1:47990:127.0.0.1:47990 gpu-server
```

随后用户访问 `https://127.0.0.1:47990` 并提交 Moonlight 显示的 PIN。管理页不需要远端实体屏幕。

在历史 Sunshine 0.23.1 的特定无头环境中，桌面通知服务激活等待曾阻塞配对。只有重现该日志证据时，才给 **Sunshine 单个进程**隔离通知 D-Bus；不改共享总线。此为版本特定诊断，不作为所有新版本的默认设置。

键鼠可能使用 XTest 回退；有回退不能直接判定游戏不可玩。若确需 uinput，要限制设备权限及进入的专用 seat/display，不能全局开放其他用户的输入设备。原实践中相对鼠标 + XTest 已通过用户操控验证。

### B3. Steam、游戏与兼容工具

- Steam 只运行一个隔离客户端。用户自行登录，合法安装/上传游戏；不提交 Steam userdata、登录票据或游戏内容到 GitHub。
- 核对所选 GE-Proton 以及 toolmanifest 要求的 Steam Linux Runtime 已由正常 Steam 安装注册；“下载了 tar”不等于 Steam 已完成注册。
- 将游戏的专用 `STEAM_COMPAT_DATA_PATH` 固定到稳定目录，保留存档、隐私选择和已安装依赖。Steam 标准空目录与真实 pfx 要区分；不得覆盖已有 prefix。
- 启动时设置足够的 nofile，明确 NVIDIA ICD 与目标 Vulkan device。设备编号按本机枚举核验，不能因 GPU 型号相同就认为筛选了唯一 GPU。
- 如果 MFC/Chroma 加载报缺少 `mfc140u.dll`，从 Microsoft 官方来源取得相应运行库，验签后只安装进该 prefix；不随意删除原游戏 DLL。
- 先在线准备并启动一次，再正常退出游戏并切 Steam 离线；离线仍缺组件时临时在线补齐，不伪造 manifest 或许可证。

若 Steam 先崩溃、游戏随后报告 IPC 断开，要查 Steam 的第一次崩溃。原实践的 NetworkManager 回调崩溃使用仅作用于该 Steam 进程的有效私有 system D-Bus 规避；只在有同类证据时采用，不能写一个无效的 D-Bus 地址冒充修复。

### B4. 监控脚本和 Steam 启动选项

本仓库 `scripts/monitor-game.sh` 是可选入口，**不是完整安装器**。把它复制到自己的 `$GPUIP_ROOT/scripts/monitor-game.sh`，并先配置真正的 prefix、GPU index、NVIDIA ICD，以及可选 MangoHud。它保留 Steam 提供的 `%command%`，不另挑一套 Proton。

在远端 Steam 的本游戏“通用 → 启动选项”填入一整行，替换示例目录与 index：

```text
GPUIP_ROOT=/home/user/gpu-over-ip GPUIP_GPU_INDEX=0 GPUIP_COMPAT_DATA_PATH=/home/user/gpu-over-ip/compatdata/1888930 /bin/bash /home/user/gpu-over-ip/scripts/monitor-game.sh off %command%
```

`off` 关闭这个入口中的 MangoHud / DXVK HUD；`hud` 显示帧率；`log` 增加左 Shift+F2 手动 CSV。切换前保存原启动选项，正常退出并重启游戏后生效，不影响当前进程。若 prefix 路径有空格，给环境变量赋值正确加 shell 引号。

`hud/log` 需要自己安装 MangoHud，并使 layer 路径与其库在 Steam 容器内可见。`GPUIP_MANGOHUD_LAYER_DIR` 可覆盖默认的 `$GPUIP_ROOT/runtime/mangohud/layers`。本脚本使用内联配置避免旧外部配置路径被过滤；CSV 放在同一专用 prefix 下，实际以 `/proc/<gamepid>/root` 验证其可见性与可写权限。不能把某个 `.so` 已映射等同于配置或记录已经生效。

### B5. 验收与停止

验收应包含：用户配对、NVENC 会话、音频、远端 Steam 登录、实际存档进入、实体相对鼠标正常、小幅镜头测试、正常退出释放显存。记录游戏 FPS 与视频链路数据的区别。

停止顺序：用户保存并退出游戏 → 正常退出专用 Steam → 断开 Moonlight → 停止经 UID/路径校验过的 Sunshine → 专用 Xorg → 私有音频。保留 prefix、证书与配对状态。禁止全局 killall、未知进程的 pkill、GPU reset 或为了清理游戏而重启服务器。

## C. 怎样确认远端持续运行

### C1. 机器、SSH 和应用分三层看

远端机器必须已开机、联网且 SSH 可达。本地“一键远程 Steam”能补启动已经部署的软件，不能替一台断电或没有管理通道的服务器开机。SSH 窗口关闭后，脱离 SSH 启动的后台进程可继续；这不等于机器重启后自动恢复，也不等于服务崩溃会自动重启。

当前默认机制是按需准备：每次点击本地入口，先运行远端幂等 `start-session.sh`，再检查 Steam 和 Sunshine，成功才打开 Moonlight。长期驻留与自动恢复是下面的可选配置，不会因浏览本教程就被自动启用。

### C2. 只读健康检查与一次补启动

将仓库的 `scripts/server-health.py` 安装到自己的 `$HOME/gpu-over-ip/scripts/`。Moonlight 路线检查私有 X 显示、私有音频、Sunshine 端口、本人 Steam 进程以及会话入口：

```sh
python3 "$HOME/gpu-over-ip/scripts/server-health.py" --root "$HOME/gpu-over-ip/streaming"
echo "健康检查返回码：$?"
```

JSON 中 `ready: true` 且返回码 0 表示这些基础检查通过；不代表 Steam 账号已经登录、NVENC 每帧都正常或游戏不会崩溃。端口被其他程序占用等故障仍需按实际日志处理。

需要恢复缺失服务时使用：

```sh
python3 "$HOME/gpu-over-ip/scripts/server-health.py" --root "$HOME/gpu-over-ip/streaming" --ensure
```

`--ensure` 只在检查失败时调用已有的 `start-session.sh`，再复查结果，不启动游戏、不重置配对、不杀现有进程。前提是该入口已按 B2 做好归属校验与幂等启动。如果旧进程卡死、端口冲突或 GPU 被占用，它会保留失败状态，不能靠反复启动冒充修复。

Juice 路线使用包含实际 `agent` 的目录：

```sh
python3 "$HOME/gpu-over-ip/scripts/server-health.py" --route juice --root "$HOME/gpu-over-ip/juice-server"
```

它核对自己的 agent、回环监听和 agent 的 nofile。实际 renderer 的 GPU 归属和继承上限仍按 A4 验证。

### C3. 可选：用户级开机启动与自动恢复

两个示例 unit 分别对应两条路线，**根据需要安装一个或分别配置，不把它们当成同一项服务**：

- `examples/gpuip-juice-agent.service`：前台运行 Juice agent，异常退出后由 systemd 重启，并设置 nofile。
- `examples/gpuip-session-watch.service`：前台运行健康巡检，每 60 秒检查并按需调用 `start-session.sh`；自己异常退出由 systemd 重启。仅准备远端 Steam，不启动游戏。

先把示例路径改成自己的真实部署路径，确认入口、权限、GPU 和会话都正确。下面以串流巡检为例，在仓库目录执行：

```sh
install -Dm644 examples/gpuip-session-watch.service "$HOME/.config/systemd/user/gpuip-session-watch.service"
systemctl --user daemon-reload
systemctl --user enable --now gpuip-session-watch.service
systemctl --user status gpuip-session-watch.service --no-pager
journalctl --user -u gpuip-session-watch.service -n 30 --no-pager
```

Juice 则把上面 unit 名换成 `gpuip-juice-agent.service`。包解压布局有额外一层时同步修改 `WorkingDirectory` 与 `ExecStart`；已有同名 agent 先正常停自己的实例，避免端口争抢。硬上限低于 unit 需要的值时，由管理员处理合适的用户管理器限制。

要在服务器重启、用户未登录时也启动 user manager，并在退出登录后保持运行，核对 linger：

```sh
loginctl show-user "$USER" -p Linger
# 按服务器策略，由本人或管理员执行；可能需要权限。
loginctl enable-linger "$USER"
```

`Linger=yes` 加上已 enable 的 user unit 才构成这里的无登录开机启动方案；仅执行 `nohup`、仅关闭 SSH 或仅 `systemctl --user start` 都不能替代它。无需为验证而立刻重启共享服务器。[systemd 登录驻留说明](https://www.freedesktop.org/software/systemd/man/latest/loginctl.html)。

### C4. 怎么关闭自动驻留

防止下次自动启动而保留当前会话：

```sh
systemctl --user disable gpuip-session-watch.service
```

准备立即停止时，先保存退出游戏和专用 Steam，再执行 `systemctl --user stop gpuip-session-watch.service`。默认 systemd 会结束该服务创建的子进程，因此不要在游戏中把它当成纯粹隐藏巡检窗口的开关。Juice 同理先正常关闭自己的客户端应用，再停对应 unit。是否关闭 linger 应考虑该用户其他 user 服务，不默认全局关闭。

## Agent 交接结果格式

```text
route: juice | streaming
version_pair: 相同 / 不相同（具体公开版本）
ssh: ready | failed
target_gpu: 已私下核对，公开报告不含 UUID
agent_loopback: ready | failed
nofile_agent_and_renderer: 已核验 / 未核验
graphics_sample: pass | fail | not-tested
actual_game_scene: 具体场景 / not-tested
input: 实体鼠标确认 / not-tested
performance_scope: gameplay | startup-menu | stream-only | not-measured
remaining: 依赖、许可或兼容性阻塞
```

参考：[Juice 历史发行版](https://github.com/Juice-Labs/Juice-Labs/releases)、[Sunshine 文档](https://docs.lizardbyte.dev/projects/sunshine/latest/)、[GE-Proton releases](https://github.com/GloriousEggroll/proton-ge-custom/releases)、[MangoHud 0.6.5 配置](https://github.com/flightlessmango/MangoHud/blob/v0.6.5/bin/MangoHud.conf)。
