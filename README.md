# Win11 任务栏内嵌待办（Taskbar Todo）

> 🔬 **本项目是一个以科研为主的实验性工程**，核心目标是探索并验证一套
> 在 **Windows 11 任务栏内部**渲染自定义半透明 UI 的技术方案，
> 并非面向最终用户的生产级产品。

把待办事项以**半透明圆角 pill** 直接嵌入 Windows 11 系统任务栏，
像系统自带组件一样融入 acrylic 材质。本项目聚焦于以下底层技术课题的
可行性研究与原型验证：

| 研究课题 | 涉及技术 |
|---------|---------|
| 如何在任务栏"内部"绘制半透明 UI | `SetParent` 嵌入 + `UpdateLayeredWindow` 逐像素 alpha 分层窗口 |
| 逐像素 alpha 合成替代 Tk 不透明渲染 | Pillow（PIL）RGBA 位图合成 |
| GIL / 多线程环境下的 Win32 交互安全 | 纯 Python→C 单向调用轮询，**规避** ctypes `WNDPROC` 回调 |
| 跟随系统 acrylic 主题 | 屏幕像素采样 + 注册表主题检测 + 壁纸变化重绘 |
| 中文输入法在自定义分层窗口中的承载 | 混合架构：分层窗口渲染 + Tk `Toplevel` 承载 IME |

---

## 一、研究背景与动机

Windows 任务栏（`Shell_TrayWnd`）是系统级 acrylic 表面，传统方案（如普通
`WS_EX_LAYERED` 窗口贴色块、或贴一张不透明位图）无法真正"融入"任务栏的
半透明 + 模糊效果，视觉上永远是补丁感的死色块。

本项目验证了一种 **"C-lite 渲染"** 方案：

```
待办数据  →  PIL 合成 RGBA 位图  →  UpdateLayeredWindow 逐像素混合  →  透明地叠在任务栏上
```

由于任务栏本身已是半透明 acrylic，在其之上再叠一层**半透明** pill，
下方的模糊壁纸会从 pill 底透上来——从而在视觉上达成"原生 acrylic 卡片"
的效果，而非色块补丁。

---

## 二、核心技术难点（已解决的工程问题）

### 1. 逐像素 alpha 半透明渲染
- **问题**：Tkinter 只能画不透明像素，无法实现真正的半透明叠加。
- **方案**：用 Pillow 逐像素合成带 alpha 通道的 RGBA 位图，再通过
  `UpdateLayeredWindow` 提交给 DWM 合成器。

### 2. 多线程环境下的 Win32 回调崩溃
- **问题**：用 ctypes 注册 `WNDPROC` 回调处理窗口消息时，在 Tk mainloop +
  pystray 后台线程的混合环境下会触发 **GIL / 线程状态 fatal crash**。
- **方案**：窗口类直接使用系统自带 `DefWindowProc`（纯 C，无 Python 回调），
  鼠标交互改为上层用 `root.after` 轮询 `GetCursorPos` + `GetAsyncKeyState`
  实现——**全程 Python→C 单向调用**，彻底规避 C→Python 回调路径。

### 3. 任务栏嵌入与定位
- **问题**：如何精确找到任务栏空闲区域并嵌入，不与系统图标重叠。
- **方案**：`APPBARDATA` + `ABM_GETTASKBARPOS` 获取任务栏矩形，
  枚举子窗口 class（`MSTaskListWClass` 等）定位空闲区域，
  `SetParent` 将窗口嵌入 `Shell_TrayWnd`。

### 4. 跟随系统主题
- **问题**：深/浅色、强调色、壁纸变化时需自动适配。
- **方案**：屏幕像素采样任务栏真实背景色 + 注册表读取主题与强调色 +
  定时轮询检测变化后重绘。

### 5. 中文输入法承载
- **问题**：分层窗口无法承载文本输入 / IME。
- **方案**：**混合架构**——输入浮层用 Tk `Toplevel`（支持中文输入法），
  样式/字体/高度/圆角对齐 todo pill，视觉上"在栏里新建一条待办"。

---

## 三、功能演示

- **原生融合**：C-lite 渲染，真正半透明地叠在任务栏上
- **原生中文字体**：Microsoft YaHei UI
- **交互**
  - 左键点圆圈 ○ → 切换完成（绿勾 + 删除线）
  - 左键点文字 → 就地内联编辑
  - 右键 → 菜单（完成 / 优先级 / 删除）
  - ＋ → 栏内内联输入新待办（支持中文输入法，可连续添加）
- **跟随系统**：深/浅色主题、强调色、壁纸变化自动重采样重绘
- **系统托盘**：显示/隐藏、清除已完成、设置、退出
- **设置**：字体大小、数据存储路径、**开机自启**

---

## 四、运行环境（源码）

> **仅支持 Windows 10 / 11**（依赖 Win32 API）。

```bash
pip install -r requirements.txt
python run.py
```

---

## 五、打包为单文件 exe（可选）

```powershell
pip install pyinstaller
./build.ps1            # 或 bash build.sh，或 pyinstaller TaskbarTodo.spec
```

输出：`dist/TaskbarTodo.exe`（单文件、无控制台）。

> ⚠️ 打包产物（`build/`、`dist/`、`assets/` 图标）已通过 `.gitignore` 排除，
> 不会入库，请本地自行构建。

---

## 六、开机自启

设置对话框勾选「开机自启」即可。原理：写入注册表
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`（用户级，无需管理员）。

- 打包运行：自启命令 = exe 路径
- 源码运行：自启命令 = `pythonw run.py`

---

## 七、目录结构

```
taskbar_plugin/
├── run.py                 # 入口点
├── build.ps1 / build.sh   # 打包脚本
├── TaskbarTodo.spec       # PyInstaller 配置（含 conda Tcl/TK 版本冲突修复）
├── requirements.txt       # 运行依赖
├── assets/                # 图标资源（不入库，见 .gitignore）
└── src/
    ├── app.py             # 主应用编排（隐藏 Tk root 跑事件循环 + 分层 bar）
    ├── appbar.py          # Win32：任务栏定位/嵌入/主题/acrylic/圆角
    ├── bar_renderer.py    # PIL 合成待办位图 + 命中区域（纯计算，可独立导出 PNG）
    ├── layered_window.py  # 分层叠加窗口（UpdateLayeredWindow + 鼠标轮询）
    ├── bar_ui.py          # 内联输入 chip + 右键菜单（Tk，支持中文输入法）
    ├── todo_manager.py    # 数据模型 + JSON 持久化
    ├── config.py          # 用户设置持久化
    ├── settings_dlg.py    # 设置对话框（sv-ttk Fluent 主题）
    ├── tray.py            # 系统托盘（pystray）
    └── autostart.py       # 开机自启（注册表 Run 键）
```

数据与配置默认存于 `%APPDATA%/TaskbarTodo/`（存储路径可在设置中修改）。

---

## 八、⚠️ 科研性质声明

- 本项目是**技术探索与原型验证**，主要价值在于上述 Win32 分层窗口 /
  逐像素 alpha 渲染 / 多线程安全交互等技术课题的**研究文档与可运行参考实现**。
- 不保证在所有 Windows 版本 / DPI / 主题配置下的稳定性与兼容性。
- 任务栏内部 UI 注入属于非官方技术手段，未来 Windows 更新可能导致行为变化。
- 欢迎以此作为技术参考进行学习与二次研究。
