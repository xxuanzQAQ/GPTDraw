"""gpt帮助 的图片版：用 pytakumi 把 HTML 卡片渲染成 PNG。"""

from __future__ import annotations

import html as html_lib
from dataclasses import dataclass

from gsuid_core.utils.html_render import render_html_to_bytes

from ..version import GPTDraw_version

CSS_WIDTH = 520
_DPR = 2


@dataclass(frozen=True)
class _Row:
    command: str
    desc: str


@dataclass(frozen=True)
class _Section:
    title: str
    accent: str
    rows: tuple[_Row, ...]


_SECTIONS: tuple[_Section, ...] = (
    _Section(
        title="开始使用",
        accent="#818cf8",
        rows=(
            _Row("gpt设置密钥 <密钥>", "绑定你的 New API 密钥，建议私聊发送"),
            _Row("gpt我的密钥", "查看已绑定的密钥"),
            _Row("gpt删除密钥 [序号|全部]", "删除已绑定的密钥"),
        ),
    ),
    _Section(
        title="模型",
        accent="#a78bfa",
        rows=(
            _Row("gpt模型列表 [关键词|全部]", "查看当前密钥可用的模型"),
            _Row("gpt切换模型 <序号|模型名>", "切换之后生图使用的模型"),
            _Row("gpt当前模型", "查看当前使用的模型"),
            _Row("gpt切换模型 默认", "恢复配置里的默认模型"),
        ),
    ),
    _Section(
        title="生图",
        accent="#22d3ee",
        rows=(
            _Row("gpt生图 / gpt画图 / gptbnn", "文生图，三个命令等价"),
            _Row("附带一张图", "这张图作为参考图改图"),
            _Row("1:1 / 16:9 / 2k", "写进提示词，自动识别画幅与分辨率"),
            _Row("--model / --size", "临时换模型、指定画幅"),
            _Row("--format gif / --frame_count", "输出动态 GIF，可调帧数与帧间隔"),
            _Row("--quality / --background", "质量与背景"),
        ),
    ),
    _Section(
        title="预设",
        accent="#f59e0b",
        rows=(
            _Row("gpt预设列表", "查看可用预设"),
            _Row("gpt预设 <名称> [额外提示词]", "用预设生图"),
            _Row("gpt预设添加 <名称> <提示词>", "添加本地预设"),
            _Row("gpt重载预设库", "立即同步远程提示词库"),
        ),
    ),
    _Section(
        title="授权",
        accent="#34d399",
        rows=(
            _Row("gpt授权本群开启 / 关闭", "让本群成员用你的密钥生图"),
            _Row("gpt授权 / 取消授权 @某人", "允许或收回对方私聊使用"),
            _Row("gpt授权状态", "查看当前授权情况"),
        ),
    ),
)

_CSS = """
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: #070b16; color: #e2e8f0;
  font-family: "MiSans", "Twemoji Mozilla", sans-serif;
}
.wrap {
  width: 100%; padding: 20px 20px 16px 20px;
  background: linear-gradient(160deg, #101a33 0%, #0b1224 45%, #0a0f1e 100%);
}
.hero { display: flex; align-items: center; gap: 14px; }
.logo {
  width: 54px; height: 54px; border-radius: 17px; display: flex;
  align-items: center; justify-content: center; font-size: 29px;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 45%, #22d3ee 100%);
  box-shadow: 0 8px 24px rgba(99, 102, 241, 0.35);
}
.titles { flex: 1; display: flex; flex-direction: column; gap: 4px; }
.title { font-size: 26px; font-weight: 800; color: #f8fafc; letter-spacing: 1px; }
.sub { font-size: 12px; color: #94a3b8; letter-spacing: 0.5px; }
.ver {
  font-size: 11px; color: #c7d2fe; padding: 4px 10px; border-radius: 999px;
  background: rgba(99, 102, 241, 0.16); border: 1px solid rgba(129, 140, 248, 0.35);
}
.hr {
  height: 1px; margin: 14px 0 12px 0;
  background: linear-gradient(90deg, rgba(99, 102, 241, 0), rgba(99, 102, 241, 0.6),
    rgba(34, 211, 238, 0));
}
.chips { display: flex; gap: 8px; }
.chip {
  font-size: 11px; color: #a5b4fc; padding: 4px 10px; border-radius: 999px;
  background: rgba(99, 102, 241, 0.1); border: 1px solid rgba(99, 102, 241, 0.22);
}
.sec {
  margin-top: 10px; padding: 11px 13px 5px 13px; border-radius: 15px;
  background: #0f172c; border: 1px solid rgba(148, 163, 184, 0.14);
}
.sec-head { display: flex; align-items: center; gap: 8px; margin-bottom: 2px; }
.dot { width: 4px; height: 14px; border-radius: 2px; }
.sec-title { font-size: 14px; font-weight: 700; letter-spacing: 2px; }
.row {
  display: flex; align-items: center; gap: 9px; padding: 5px 0;
  border-top: 1px solid rgba(148, 163, 184, 0.07);
}
.row.first { border-top: 0; }
.cmd {
  flex: 0 0 auto; font-family: "Mono", "MiSans", "Twemoji Mozilla";
  font-size: 12px; color: #a5f3fc; padding: 3px 8px; border-radius: 8px;
  background: rgba(34, 211, 238, 0.08); border: 1px solid rgba(34, 211, 238, 0.18);
}
.desc { flex: 1; font-size: 12px; color: #94a3b8; line-height: 1.35; }
.tips {
  margin-top: 12px; padding: 10px 13px; border-radius: 14px;
  background: rgba(99, 102, 241, 0.06); border: 1px solid rgba(99, 102, 241, 0.16);
  display: flex; flex-direction: column; gap: 5px;
}
.tip { font-size: 12px; color: #94a3b8; line-height: 1.4; }
.accent { color: #a5b4fc; font-weight: 700; }
.foot { margin-top: 13px; text-align: center; font-size: 11px; color: #64748b; }
"""


def _row_html(row: _Row, first: bool) -> str:
    css_class = "row first" if first else "row"
    command = html_lib.escape(row.command, quote=False)
    desc = html_lib.escape(row.desc, quote=False)
    return f'<div class="{css_class}"><span class="cmd">{command}</span><span class="desc">{desc}</span></div>'


def _section_html(section: _Section) -> str:
    rows = "".join(_row_html(row, index == 0) for index, row in enumerate(section.rows))
    title = html_lib.escape(section.title, quote=False)
    return (
        '<div class="sec"><div class="sec-head">'
        f'<span class="dot" style="background:{section.accent}"></span>'
        f'<span class="sec-title" style="color:{section.accent}">{title}</span></div>'
        f"{rows}</div>"
    )


def build_help_html() -> str:
    sections = "".join(_section_html(section) for section in _SECTIONS)
    version = html_lib.escape(GPTDraw_version)
    return f"""<!DOCTYPE html>
<html lang="zh">
<head><meta charset="utf-8"><style>{_CSS}</style></head>
<body>
  <div class="wrap">
    <div class="hero">
      <div class="logo">🎨</div>
      <div class="titles">
        <div class="title">GPTDraw 生图</div>
        <div class="sub">gpt画图 · gpt生图 · gptbnn</div>
      </div>
      <div class="ver">v{version}</div>
    </div>
    <div class="hr"></div>
    <div class="chips">
      <span class="chip">New API 密钥</span>
      <span class="chip">异步任务</span>
      <span class="chip">提示词预设</span>
    </div>
    {sections}
    <div class="tips">
      <div class="tip"><span class="accent">画幅</span> 1:1 / 16:9 / 9:16 / 4:3 / 3:4 / 3:2 / 2:3 / 5:4 / 4:5 /
        21:9 或 auto；一次生成 1 张</div>
      <div class="tip"><span class="accent">提醒</span> 群里发密钥会留在聊天记录里，建议私聊绑定</div>
    </div>
    <div class="foot">GPTDraw v{version} · 发送「gpt帮助」随时查看</div>
  </div>
</body>
</html>"""


async def render_help_image() -> bytes:
    return await render_html_to_bytes(
        build_help_html(),
        max_width=CSS_WIDTH * _DPR,
        dpi=96 * _DPR,
        font_name="MiSans",
        root_max_width=CSS_WIDTH,
        image_format="png",
        lang="zh",
    )
