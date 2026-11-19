# DocLib 2.0 第三方组件与许可

本项目自身沿用上游 DocLib 的 MIT 许可（见 `LICENSE`）。v2.0 新增的前端依赖全部本地 vendored，运行时不访问 CDN。

| 组件 | 版本 | 许可 | 用途 | 文件 |
|---|---|---|---|---|
| Cytoscape.js | 3.35.0 | MIT | 关系图谱 Canvas 渲染/交互 | `doclib/web/static/vendor/cytoscape.min.js` |
| cytoscape-fcose | 2.2.0 | MIT | 力导向布局扩展 | `doclib/web/static/vendor/cytoscape-fcose.js` |
| cose-base | 2.2.0 | MIT | fcose 依赖 | `doclib/web/static/vendor/cose-base.js` |
| layout-base | 2.0.0 | MIT | cose-base 依赖 | `doclib/web/static/vendor/layout-base.js` |
| marked | 15.0.12 | MIT | Markdown 渲染 | `doclib/web/static/vendor/marked.min.js` |
| DOMPurify | 3.3.1 | Apache-2.0 / MPL-2.0 | Markdown/HTML 净化 | `doclib/web/static/vendor/purify.min.js` |
| Noto Sans SC / Noto Serif SC | 系统字体 | OFL 1.1（字体本身） | UI/阅读字体；**未随包分发**，使用本机安装版本 | 无 |
| Lucide 图标路径 | 参考子集 | ISC | 界面图标（手写内联 SVG 路径） | 代码内 |

说明：
- 未复制 Logseq / 思源（AGPL-3.0）代码；只参考公开交互与架构。
- 未引入 Electron/Tauri、Vue/React/Vite 等运行时或构建依赖。
- 若后续需要打包中文衬线字体，将以 OFL 子集方式加入并更新本文件。
