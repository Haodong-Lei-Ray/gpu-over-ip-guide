# 本地 Client Agent 配置指南

目标：在 Windows 保留主程序，通过 SSH 使用 Linux 的 GPU；先完成 Juice 最小图形验收，再评估具体应用。若选择 Moonlight，则完整游戏改在远端执行。

## 0. 先收集输入，再操作

需要用户或 server agent 提供：SSH alias、实际 GPU index/PCI bus、远端 agent 就绪状态、同版本客户端包、合法的本地 64 位应用路径，以及是否允许对当前网络做特定调整。把这些写在自己的私有工作笔记，不提交到本仓库。

默认保留正在维持连接的 VPN；不切全局节点、不更换驱动、不停止未知 GPU 作业。账号密码、设备授权、系统安全与隐私选择由用户本人完成。

## 1. 建立 Windows 工作目录和 SSH

```powershell
New-Item -ItemType Directory -Path 'C:\gpu-over-ip' -Force
ssh gpu-server
```

本地 `%USERPROFILE%\.ssh\config` 的示例如下，真实文件不提交：

```sshconfig
Host gpu-server
    HostName gpu-server.example
    User remote-user
    Port 22
    ServerAliveInterval 15
    ServerAliveCountMax 3
```

首次连接核对主机指纹，使用现有密钥或用户完成的认证。SSH 失败时先定位 DNS、路由、账号和端口，不把“关闭 VPN”当成默认修复。普通 SSH 与 Moonlight 的 UDP 链路需要分别验证。

## 2. 安装固定的 Juice 历史客户端

本流程选择 `2023.08.10-2103.0633b794`，需要 server 使用同一发行版。只从[官方历史 release](https://github.com/Juice-Labs/Juice-Labs/releases/tag/2023.08.10-2103.0633b794)下载 `JuiceClient-windows.zip`，解压到 `C:\gpu-over-ip\juice-client`。检查根目录实际有 `juicify.exe`、`juice.cfg`、相关 DLL 和 `vkcube.exe`；如果多嵌套了一层目录，以实际位置为准。

```powershell
$juiceArchive = 'C:\gpu-over-ip\JuiceClient-windows.zip'
Get-FileHash -Algorithm SHA256 -LiteralPath $juiceArchive
Expand-Archive -LiteralPath $juiceArchive -DestinationPath 'C:\gpu-over-ip\juice-client'
```

记录下载来源、版本和哈希；自己计算的哈希只能用于后续一致性比较，不能冒充独立的上游签名验证。不把压缩包、DLL、私有配置或日志提交进教程仓库。当前商业产品如要求组织、授权或许可证，应走其正常流程，不借此教程修改验证逻辑。

## 3. 等待 server 就绪并建立隧道

让 server agent 按 `server.md` 启动只监听回环的 Juice agent，并返回以下非敏感结论：版本一致、监听就绪、所选 GPU 空闲/获准使用、渲染子进程可继承足够的 nofile。

另开一个本地 PowerShell 窗口，执行并保持运行：

```powershell
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:14321:127.0.0.1:43210 gpu-server
```

不要把 agent 改成公网监听来解决隧道问题。本地 14321 已被占用时，选择其他本地回环端口，并同时修改客户端 `--address`。

## 4. 先运行 Vulkan cube

下面的 PCI bus 是占位示例，须替换成 server 枚举出的目标 GPU。

```powershell
Set-Location -LiteralPath 'C:\gpu-over-ip\juice-client'
New-Item -ItemType Directory -Path '..\private' -Force
.\juicify.exe --juice-path . --address 127.0.0.1:14321 --pcibus 01:00.0 --log-level error --log-file '..\private\juice-client.log' .\vkcube.exe
```

注意：`--address` 是此固定发行版的参数；不要混用更早 `--host` 或新产品 CLI 的语法。默认用 ERROR，只有定位故障时才临时提高日志级别。

验收需同时满足：本地实际出现并更新 cube 画面；server 确认属于本次应用的 renderer 进程和目标 GPU 有相应活动；正常关闭后对应渲染会话释放。不要根据已有的无关计算负载认定成功。

## 5. 再替换为自己的游戏

先确认该程序的位数和图形 API；Steam 游戏先打开本地 Steam。保留该应用原本需要的启动方式，不绕过 Steam、反作弊或许可证。示例：

```powershell
Set-Location -LiteralPath 'C:\gpu-over-ip\juice-client'
.\juicify.exe --juice-path . --address 127.0.0.1:14321 --pcibus 01:00.0 --log-level error --log-file '..\private\game.log' 'C:\Games\ExampleGame\game.exe'
```

原实践中 32 位入口不成功，不能假定本包支持所有 x86 游戏。把数据交给某个 64 位兼容运行器，是特定游戏的另一种运行方式，不等于把任意 32 位 EXE 变成兼容。也不能把 NVIDIA CUDA 可用等同于 D3D12 游戏兼容。

GPU-over-IP 不要求预先上传整个游戏，但会在运行中传输图形资源；大型游戏仍可能极慢。记录加载、实际场景、缓存、帧时间、网络往返和远端利用率。低利用率不必然意味着驱动故障，也可能是 API 往返或同步瓶颈。

## 6. 可选：Moonlight 客户端

当用户接受远端安装游戏时，按 server 指南建立独立串流会话。下载官方 Moonlight Windows 客户端；使用便携版时，始终从有 `portable.dat` 的目录启动，避免换了一套客户端身份。

将下面的示例主机替换成自己的可达地址；Sunshine 的应用列表须包含名为 `Steam` 的应用，或使用 server 实际配置的名称。

```powershell
Set-Location -LiteralPath 'C:\gpu-over-ip\moonlight'
.\Moonlight.exe stream --1080 --fps 60 --bitrate 8000 --video-codec H.264 --video-decoder hardware --no-hdr --display-mode windowed --no-performance-overlay --no-absolute-mouse gpu-server.example "Steam"
```

首次配对由用户在本地 Sunshine 管理页面提交当前 PIN。Steam 在远端单独登录，游戏在远端启动。对于 Proton，先确认兼容工具及它要求的 Steam Linux Runtime 已实际安装注册，再测试离线；本地 Windows 启动过不能代替远端首次准备。

### 日常一键启动远程 Steam

完成 server 配置后，将 `examples/launcher.example.json` 复制为本机 `private/launcher.json` 并填写真实参数；此私有文件已被 Git 忽略。`remote_root` 是包含 `scripts/start-session.sh` 和 `runtime/steam-client` 的实际串流部署目录。

本地 Python 3.10+（带 tkinter）运行：

```powershell
python scripts/open_remote_steam.py --config private/launcher.json --check-only
pythonw scripts/open_remote_steam.py --config private/launcher.json
```

本地 agent 可为第二条命令创建桌面“启动远程 Steam”快捷方式，工作目录设成本地项目目录。开机后让既有 VPN 就绪，双击一次即可：检查 SSH → 复用/补启动专用会话 → 等待 Steam/Sunshine 就绪 → 打开 Moonlight。它不执行 `-applaunch`，不自动启动任何游戏；用户在远端 Steam 库里选择游戏。首次 SSH、过期的 Steam 登录或系统权限提示仍由用户完成。

`--check-only` 只读检查；`--prepare-only` 仅准备远端服务、不打开本地窗口。远端就绪入口须由 server agent 预先建立，公开脚本不是完整服务器安装器。

如果普通 SSH 被现有 VPN 路径影响，可在自己的配置中启用 `direct_ssh_fallback` 并填写与 SSH HostName 一致的 `direct_ssh_host`。它只在普通 SSH 连接失败后，为 SSH socket 绑定恰好一块启用的物理网卡；不修改路由或 VPN。多网卡、策略或网络环境不满足时会报错，不猜测接口，也不替 Moonlight UDP 改道。

### 鼠标与监控

| 快捷键 | 作用 |
| --- | --- |
| Ctrl + Alt + Shift + S | Moonlight 视频传输统计显隐 |
| Ctrl + Alt + Shift + M | 切换鼠标模式，游戏使用相对模式 |
| Ctrl + Alt + Shift + Z | 捕获/释放键鼠 |
| Ctrl + Alt + Shift + X | 全屏/窗口 |
| Ctrl + Alt + Shift + Q | 断开串流，远端游戏继续 |
| 右 Shift + F12 | 已启用 MangoHud 时切换游戏 HUD |
| 左 Shift + F2 | 已配置输出目录时开始/停止 MangoHud CSV |

`--no-performance-overlay` 只关闭 Moonlight 自身统计。MangoHud、DXVK HUD、Steam 性能监视器分别关闭；不要为去掉屏幕上的 VKD3D 字样删除 D3D12 转译组件。监控启动选项及可选脚本见 `server.md` 与 HTML。

### 每次默认全屏

临时切换：先点击 Moonlight，让它获得焦点，按 **Ctrl + Alt + Shift + X**，再按一次回到窗口。被键鼠捕获困住时可按 Ctrl+Alt+Shift+Z 释放。

希望一键入口今后默认全屏，在本机私有 `launcher.json` 设置 `"display_mode": "fullscreen"`；`windowed` 为窗口，`borderless` 为无边框。下次重新连接生效，不自动断开当前会话。自己手动运行 CLI 时，将 `--display-mode windowed` 换成 `--display-mode fullscreen`。

### 确认远端确实就绪

本地可执行 `python scripts/open_remote_steam.py --config private/launcher.json --check-only`，查看 SSH、会话入口、Steam 与 Sunshine 状态。完整显示/音频检查和可选长驻服务见 server.md 的 C 节。服务器开机自启与当前一键入口的“按需补启动”不同，不能只因退出 SSH 后还在运行就声称已配好开机恢复。

## 7. 结束与交接

Juice：先正常退出本地应用，确认 renderer 释放，再关闭自己建立的 SSH 隧道。Moonlight：要结束游戏，先在游戏内保存并退出；仅断开画面不会释放游戏显存。

交给用户的最终报告包括：路线 A/B、版本、应用位数与 API、两端就绪状态、实际进入的场景、网络和帧率测量范围、已知失败、重连/退出命令。报告对公网脱敏，只在私有沟通中交换真实地址或 UUID。

### 出错时的优先顺序

1. SSH/隧道 → 版本和 CLI 语法 → GPU 选择 → 简单样例 → 具体游戏。
2. `Too many open files`：让 server 查 agent 及 renderer 的 `/proc/<pid>/limits`，提高 agent 启动前的限制后再创建新会话。
3. “主机未配对”：核对便携版工作目录，不清空原服务器证书。
4. 旋转失控：检查相对鼠标，不只调游戏灵敏度。
5. 黑屏：区分加载、游戏退出、Steam 退出、串流断线；留存私有日志，不上传崩溃转储。

参考：[Juice release 参数变更](https://github.com/Juice-Labs/Juice-Labs/releases/tag/2023.08.10-2103.0633b794)、[Moonlight 官方快捷键](https://github.com/moonlight-stream/moonlight-docs/wiki/Setup-Guide#keyboardmousegamepad-input-options)。
