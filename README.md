# Chakram X 鼠标配置

适用于 Windows x64 的 ROG Chakram X 配置工具。程序直接通过 Windows HID 设置 DPI、侧键、摇杆、板载预设和 RGB 灯效，可在普通用户权限下运行。设置保存在鼠标上，配置完成后可以关闭程序。程序不连接网络，也不调用 Armoury Crate 的服务或 DLL。

从 [GitHub Releases](https://github.com/RhoninSeiei/ChakramXControl/releases/latest) 下载 `ChakramXControl.exe`，双击即可使用。同一版本提供第三方许可文本和 `SHA256SUMS.txt`。如需核对下载文件，在 PowerShell 运行 `Get-FileHash .\ChakramXControl.exe -Algorithm SHA256`，与校验清单中的 EXE 条目比较。

## 操作

1. 使用 USB 线连接鼠标，或连接原配 2.4 GHz 接收器并唤醒鼠标。点击“刷新设备”。如果同时发现多只设备，可在右上角选择。
2. 选择板载预设 1 至 5，点击“切换预设”后再编辑。启动和刷新只读取设备。
3. 在“灵敏度”查看高亮并标有“使用中”的档位。用鼠标实体键切换时，打开的窗口约每 1.5 秒更新一次，即使两档 DPI 数值相同，也按实际档号标记。输入目标 DPI 并点击同一行的“保存数值”可设置两轴并保留该档指示颜色。“启用此档”用于切换档位。
4. “四个侧键”分别显示实际绑定和待保存动作。修改 A、B、C、D 的动作后，点击对应的“保存按键”。现有的未知动作按十六进制显示。

## 灯效

在“灯效”页选择徽标、滚轮、前端灯带或全部灯区。单个灯区支持常亮、呼吸、颜色循环、触发和关闭，全部灯区还支持彩虹、彗星和电量指示。选择效果后可调整亮度，单色效果支持 Windows 选色器和十六进制色值。彩虹可以设置方向和速度，彗星可以设置方向和随机颜色。

页面顶部显示各灯区从设备读到的实际效果、亮度及适用的颜色和动画参数。编辑选项后点击“保存到当前预设”，程序写入鼠标并读取三个灯区核对结果。切换到其他板载预设后可单独设置灯光。

## 侧面摇杆

打开“侧面摇杆”。页面顶部的兼容模式对整只鼠标生效，四方向映射可在预设 1 至 4 中单独编辑。

- **游戏手柄**　选择“模拟摇杆 · 纵向”或“模拟摇杆 · 横向”，点击“应用摇杆设置”。程序启用鼠标的游戏手柄接口，等 Windows 重新枚举后写入对应的两轴映射。“测试控制器”打开 Windows 游戏控制器面板，可在 ROG CHAKRAM X 的属性中观察 X、Y 轴。
- **四个按键**　选择“数字四键”，分别指定上、下、左、右的动作，然后点击“应用摇杆设置”。四个普通侧键仍可在自己的页面独立配置。选择键盘动作时，可打开“测试按键输入”并实际拨动摇杆。
- **摇杆兼容模式**　勾选后，Windows 隐藏这只鼠标的手柄接口；取消勾选后，Windows 可将它识别为游戏手柄。勾选状态来自鼠标固件，旁边的文字显示 Windows 实际检测结果。应用数字四键时保留原开关状态，应用模拟摇杆时自动关闭兼容模式。

方向设置只在点击“应用摇杆设置”时写入。鼠标对方向写入提供应答，当前协议无法读回四个方向的原始绑定。界面会标明本机上次成功提交的布局，首次使用提供四个方向键作为待写入值。本机记录位于 `%LOCALAPPDATA%\ChakramXControl\settings.sqlite3`，按物理设备和预设分开保存。其他工具或设备重置可能使该记录与实际映射不同。

## 支持和验证范围

**独立运行。** 在 Windows x64 上只需复制 `ChakramXControl.exe`。程序自带 Python、Tk、SQLite 和 hidapi，配置命令通过 Windows HID 接口发给鼠标。DPI、预设、侧键、摇杆和板载灯效都使用这条通道。程序不会从 Armoury Crate 导入配置，摇杆写入记录由本程序在当前 Windows 用户下维护。

**验证边界。** 本机有线配置接口使用 Microsoft 的 `input.inf` 和 `HidUsb`。发布包曾单独复制到空目录，以空应用数据目录和仅含 Windows System32 的 PATH 启动，读到了鼠标的活动预设、DPI 档位及数值；检查时程序未加载华硕模块。当前机器安装了 Armoury Crate，驱动栈也有第三方过滤器。干净 Windows 上对实物全部功能的验收仍待完成。

有线型号 `0B05:1A18` 已实机验证 DPI 数值、DPI 档位、侧键、板载预设的更改与恢复，并验证了游戏手柄接口在 Windows 中的出现与消失。启用时 Windows 枚举出同一物理设备的 `MI_04`，其 HID 描述符包括 X 和 Y 两个轴。四方向报文依据原厂 P708 实现校对，实际拨动产生的输入需在使用时测试。原配 2.4 GHz 接收器 `0B05:1A1A` 有代码支持，本次仅实测有线模式。

公开型号与协议参考见 [G-Helper ChakramX](https://github.com/seerge/g-helper/blob/main/app/Peripherals/Mouse/Models/ChakramX.cs)、[G-Helper AsusMouse](https://github.com/seerge/g-helper/blob/main/app/Peripherals/Mouse/AsusMouse.cs) 和 [华硕型号说明](https://rog.asus.com/support/faq/1050027/)。摇杆兼容开关及模拟轴编码另与本机原厂 MouseSDK 和 P708 HAL 静态核对。

## 从源码运行

Windows x64 上使用 Python 3.13 和 Tk。生成的单文件程序包含运行环境。

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe app.py
```

## 构建与发布

在 Windows 的 PowerShell 7 中运行 `./scripts/build.ps1 -Python .\.venv\Scripts\python.exe`。脚本执行测试、构建单文件程序、检查打包入口，并在 `dist` 下生成 EXE、第三方许可说明和 SHA-256 校验清单。CI 使用 Windows x64 运行器，无需连接鼠标；硬件验证范围见上文。

推送到 `main` 或提交 Pull Request 会触发 Windows 构建。维护者推送形如 `v0.1.0` 的带注释标签后，发布工作流从该标签重建，核对校验和，将产物发布到 GitHub Releases。标签注释用作该版本的发行说明。[构建与发布工作流](.github/workflows/windows.yml)

## 协议与许可

HID 文档包含报文封装、读写命令、摇杆兼容开关、灯区应答差异，以及各功能的验证边界。[HID 协议文档](docs/hid-protocol.md)

本项目源码使用 MIT 许可证。随发布包分发的第三方组件保留各自的许可。ROG 和 Armoury Crate 为华硕的产品名称，本项目由社区独立开发。[项目许可证](LICENSE) · [第三方组件说明](THIRD_PARTY_NOTICES.md)
