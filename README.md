# GPU-over-IP Guide

面向人类操作者和两端 agent 的远程 GPU 实践手册。包含真正的图形 API 转发，以及远端运行游戏、回传视频的备选方案。公开版本中的主机、账号、目录与 GPU 地址均为示例。

**[在线操作手册 / 项目官网](https://haodong-lei-ray.github.io/gpu-over-ip-guide/)** · [本地 client agent](client.md) · [远端 server agent](server.md)

## 从哪里开始

| 文件 | 读者 | 作用 |
| --- | --- | --- |
| [client.md](client.md) | 本地 Windows client agent | 检查 SSH 与版本，建立隧道，选择远端 GPU，启动本地应用，验证真正使用了远端渲染；也包含 Moonlight 的连接与监控开关。 |
| [server.md](server.md) | 远端 Linux server agent | 安装并隔离 Juice agent，核查驱动、GPU、文件描述符与监听地址；需要串流时再配置独立桌面、音频、Sunshine、Steam/Proton。 |
| [index.html](index.html) | 人类操作者 | 可离线阅读的操作页。填写自己的参数，生成 SSH、启动与监控命令，查看退出、重连与排错说明。 |

两端 agent 先各自阅读对应文件，再交换脱敏的就绪状态。HTML 不会替你执行命令，也不会上传填写的连接参数。

日常使用：打开一个“远程 Steam 管理器”，在同一窗口从私有 `servers.json` 选择服务器，查看状态、连接/启动、切卡与关闭；点击连接时，远端 Steam 已运行就直接复用，尚未运行才按所选显卡启动。渲染与串流编码可以分别选卡；四卡状态和进程别名在同一窗口查看。全屏按 **Ctrl + Alt + Shift + X**。远端是否就绪、按需恢复以及可选开机驻留/自动巡检，见 [server.md 的 C 节](server.md#c-怎样确认远端持续运行)。默认不会替用户开启驻留服务。

## 本次同步的入口与脚本

- `scripts/steam_manager.py`：统一管理窗口；选服务器、四卡状态、连接/启动、独立选卡和关闭共用同一界面，关闭前重新检测所选主机。
- `scripts/server_profiles.py`：多服务器列表、SSH 主机/用户/端口配置和启动时选择；私有配置见 `examples/servers.example.json`。
- `scripts/open_remote_steam.py` + `quick_start.py`：按真实可执行文件与 UID 识别 Steam，已就绪时只读检测后直接连接；`--choose-gpu` 主动打开选卡。
- `scripts/gpu_picker.py` + `scripts/gpu-selector/`：分别选择 Steam/游戏渲染 GPU 和 Sunshine NVENC GPU，显示显存、GPU/编码利用率、温度、功耗、PID；游戏运行时拒绝切卡。
- `scripts/close_remote_steam.py`：选择目标服务器后正常关闭专用会话；不关闭服务器或强制结束游戏。
- `process_aliases.py` / `nvidia_smi_names.py`：界面与可选终端包装使用一致的 `python1`、`python2` 显示别名；真实名称仍可查看，不修改程序、驱动或其他用户的进程。

服务器选卡后端依赖 `server.md` 的目录、状态文件和启动脚本契约；**先完成两端 agent 的集成，再启用选卡**。本仓库不上传原机安装器、生产配置、账号、二进制或进程改名注入组件。使用四张卡的数量与索引由服务器枚举，不把 GPU 型号相同当成设备相同。

原环境已验证一个渲染卡与编码卡分开的组合、Steam 改变启动显示名后的复用、四卡状态及游戏运行时的切换保护；其他繁忙卡未逐一实测切换。多服务器分流、参数隔离与防止复用错主机的逻辑有本地测试，未声称已完成两台真实服务器的端到端串流验收。

## 两条路线：执行位置不同

```text
A. Juice / GPU-over-IP
Windows: 本地 Steam + 本地游戏逻辑
                    ↕ 图形 API、资源与结果
Linux:   Juice agent + NVIDIA GPU

B. Sunshine + Moonlight / 远程串流
Linux:   Steam + Proton + 完整游戏 + GPU 渲染 + NVENC
                    ↓ 视频/音频     ↑ 键鼠
Windows: Moonlight
```

| 项目 | A：Juice 图形转发 | B：Moonlight 串流 |
| --- | --- | --- |
| 主程序位置 | 本地 Windows | 远端 Linux |
| 游戏主体需传到远端 | 不需要预先完整上传；运行中仍传输资源 | 需要远端安装或上传 |
| 远端 Proton | Windows 本地游戏通常不需要 | Windows 游戏通常需要 |
| 账号要求 | 本指南固定的历史社区版与当前商业产品流程不同 | 用户自己的 Steam 登录，Sunshine 本机配对 |
| 性能限制 | API 调用往返、同步、资源传输与兼容性 | 远端渲染、编码、网络和本地解码 |

**本仓库不是新的 GPU 驱动、Juice 分支或通用兼容层。** 它整理现有工具的配置与验收流程。支持 CUDA 不等于支持普通游戏，多块 GPU 也不会自动合并成一张更快的游戏显卡。

## 技术栈与版本策略

- Windows 10/11、OpenSSH、PowerShell；Linux NVIDIA 驱动与 Vulkan loader。
- Juice 历史社区发行版：`2023.08.10-2103.0633b794`。固定 client/server 同一版本，使用 `juicify.exe` 与 `agent`。这不是当前商业版本的安装说明，也不绕过任何版本的组织、许可证或登录验证。
- 串流备选：Sunshine、Moonlight、私有 Xorg、Openbox、PulseAudio、Steam、GE-Proton、VKD3D-Proton/DXVK。
- 可选监控：MangoHud。Moonlight 统计衡量视频链路，MangoHud 衡量应用提交，二者不能互相代替。
- 原始实践曾使用 Moonlight 6.2、Sunshine 0.23.1、GE-Proton9-27、MangoHud 0.6.5。它们是兼容性基线，**不是对所有新机器的推荐最新版**。选择版本前检查上游说明、当前驱动和已知安全问题。

Juice 的当前官方 FAQ 说明 Windows 客户端可使用 Linux GPU 运行图形应用；当前产品的 API、驱动要求不能直接套用到历史社区包。[官方 FAQ](https://docs.juicelabs.co/docs/juice/faq)、[历史发行版](https://github.com/Juice-Labs/Juice-Labs/releases/tag/2023.08.10-2103.0633b794)。

## 已知结果与实际限制

经过脱敏的原始实践中，简单 Vulkan 图形样例及一个使用 64 位兼容运行器的 2D 游戏完成过远端渲染。原始 32 位游戏入口没有因此被证明可用。一个大型 D3D12 游戏在 Juice 路线中出现约 7 FPS 的反馈，未完成同场景性能优化验证。

同一大型游戏的 Moonlight 路线已进入实际存档，切换到相对鼠标后，用户确认镜头操控正常。完整剧情、长期稳定性、所有游戏和通用多卡 LLM 部署均不在已验证结论内。公开示例经过语法和静态核查，读者机器仍须完成两端验收。

## 公共参数约定

| 参数 | 示例 | 配置位置 |
| --- | --- | --- |
| SSH alias | `gpu-server` | client 的私有 SSH config |
| SSH HostName | `gpu-server.example` | 替换成自己的地址；`.example` 是保留示例域名 |
| 本地工作目录 | `C:\gpu-over-ip` | 自己创建的目录，第三方包不放进 Git |
| 远端工作目录 | `/home/user/gpu-over-ip` | 对应远端用户拥有的目录 |
| GPU index / PCI bus | `0` / `01:00.0` | 必须由 server 实际枚举，不照抄示例 |
| Juice 服务端 / 本地隧道 | `127.0.0.1:43210` / `127.0.0.1:14321` | 服务仅回环监听，经 SSH 访问 |

## 两端共同验收

1. SSH 可达，GPU 的 index、PCI 地址、UUID 与占用者已核对。
2. Juice client/server 版本一致；先运行随包 Vulkan cube，再运行自己的合法应用。
3. 观察远端新渲染进程、GPU 显存/利用率变化及客户端实际画面；不能只看“远端有一个 python 进程”。
4. 应用正常关闭后，自己建立的隧道和渲染会话释放；不影响其他人的计算作业。
5. 对游戏报告实际场景、分辨率、缓存状态、测量时长和帧时间，菜单或视频 60 FPS 不作为游戏性能结论。

## 发布与脱敏

本仓库仅包含文档、网页和自行编写的示例，不分发游戏、驱动、第三方二进制、账号数据或生产日志。真实 IP、SSH 私钥、Token、Steam userdata、Sunshine 证书/配对状态、GPU UUID 和绝对个人目录都不应提交。

发布前运行 `python scripts/audit_public.py`。它检查常见凭据、非示例 IPv4、个人 Windows 目录、GPU UUID、禁止的运行态文件及 Markdown 文件数量；这是辅助检查，不能替代人工审阅。新增文件应显式 `git add`，不要对包含运行环境的父目录执行 `git add .`。

网站使用 GitHub Pages，从 `main` 分支根目录发布 `index.html`；`.nojekyll` 保留原始静态文件。公开仓库可使用 GitHub Free 的 Pages 项目地址 `https://<owner>.github.io/<repository>/`，无需购买域名。[GitHub Pages 说明](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)。Pages 地址用于静态手册；GPU 连接仍使用读者自己的网络与 SSH。网页没有本项目的外部统计代码；托管平台的基础访问日志由平台自身处理。

## 上游资料

- [Juice 社区发行版](https://github.com/Juice-Labs/Juice-Labs/releases)
- [Juice 当前文档](https://docs.juicelabs.co/)
- [Sunshine](https://docs.lizardbyte.dev/projects/sunshine/latest/)
- [Moonlight 设置与快捷键](https://github.com/moonlight-stream/moonlight-docs/wiki/Setup-Guide)
- [GE-Proton](https://github.com/GloriousEggroll/proton-ge-custom/releases)
- [MangoHud](https://github.com/flightlessmango/MangoHud)

第三方软件和游戏分别遵循其原有许可与使用条件。
