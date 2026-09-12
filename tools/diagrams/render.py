"""Render the README diagrams as SVG, once per colour scheme.

Two files are needed because GitHub picks between them with ``<picture>`` and
``prefers-color-scheme``; hand-maintaining both would guarantee they drift.
So geometry and content are described once, and only the palette changes.

The backgrounds are GitHub's own canvas colours, so a diagram sits on the page
without a visible card edge around it — the drawing appears to float on the
README rather than sit in a box that does not quite match.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"


@dataclass(frozen=True, slots=True)
class Palette:
    name: str
    bg: str
    surface: str
    surface_alt: str
    border: str
    text: str
    muted: str
    accent: str
    accent_soft: str
    success: str
    success_soft: str
    danger: str
    danger_soft: str
    attention: str
    attention_soft: str


#: GitHub's light and dark canvas palettes (Primer).
LIGHT = Palette(
    name="light",
    bg="#ffffff",
    surface="#f6f8fa",
    surface_alt="#eaeef2",
    border="#d1d9e0",
    text="#1f2328",
    muted="#59636e",
    accent="#0969da",
    accent_soft="#ddf4ff",
    success="#1a7f37",
    success_soft="#dafbe1",
    danger="#cf222e",
    danger_soft="#ffebe9",
    attention="#9a6700",
    attention_soft="#fff8c5",
)

DARK = Palette(
    name="dark",
    bg="#0d1117",
    surface="#151b23",
    surface_alt="#212830",
    border="#3d444d",
    text="#e6edf3",
    muted="#9198a1",
    accent="#4493f8",
    accent_soft="#121d2f",
    success="#3fb950",
    success_soft="#0f2913",
    danger="#f85149",
    danger_soft="#2b1618",
    attention="#d29922",
    attention_soft="#2b2412",
)

TONES = {
    "neutral": lambda p: (p.surface, p.border, p.text),
    "accent": lambda p: (p.accent_soft, p.accent, p.text),
    "success": lambda p: (p.success_soft, p.success, p.text),
    "danger": lambda p: (p.danger_soft, p.danger, p.text),
    "attention": lambda p: (p.attention_soft, p.attention, p.text),
    "ghost": lambda p: (p.bg, p.border, p.muted),
}


# ── Primitives ───────────────────────────────────────────────────────────────


@dataclass(slots=True)
class Canvas:
    width: int
    height: int
    parts: list[str] = field(default_factory=list)

    def add(self, markup: str) -> None:
        self.parts.append(markup)

    def render(self, palette: Palette, *, title: str, description: str) -> str:
        body = "\n".join(self.parts)
        return f"""<svg xmlns="http://www.w3.org/2000/svg" \
viewBox="0 0 {self.width} {self.height}" width="{self.width}" height="{self.height}" \
role="img" aria-labelledby="title desc" font-family="{FONT}">
  <title id="title">{escape(title)}</title>
  <desc id="desc">{escape(description)}</desc>
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" \
markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="{palette.muted}"/>
    </marker>
    <marker id="arrow-accent" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" \
markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="{palette.accent}"/>
    </marker>
    <marker id="arrow-danger" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" \
markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="{palette.danger}"/>
    </marker>
  </defs>
  <rect width="{self.width}" height="{self.height}" fill="{palette.bg}"/>
{body}
</svg>
"""


def box(
    p: Palette,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    subtitle: str = "",
    *,
    tone: str = "neutral",
    dashed: bool = False,
    mono: bool = False,
    radius: int = 8,
) -> str:
    fill, stroke, text = TONES[tone](p)
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    lines = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"{dash}/>'
    ]
    cx = x + w / 2
    if subtitle:
        lines.append(
            f'<text x="{cx}" y="{y + h / 2 - 4}" text-anchor="middle" font-size="14" '
            f'font-weight="600" fill="{text}"'
            + (f' font-family="{MONO}"' if mono else "")
            + f">{escape(title)}</text>"
        )
        for index, part in enumerate(subtitle.split("\n")):
            lines.append(
                f'<text x="{cx}" y="{y + h / 2 + 13 + index * 14}" text-anchor="middle" '
                f'font-size="11.5" fill="{p.muted}">{escape(part)}</text>'
            )
    else:
        lines.append(
            f'<text x="{cx}" y="{y + h / 2 + 5}" text-anchor="middle" font-size="14" '
            f'font-weight="600" fill="{text}"'
            + (f' font-family="{MONO}"' if mono else "")
            + f">{escape(title)}</text>"
        )
    return "\n".join(lines)


def region(
    p: Palette,
    x: float,
    y: float,
    w: float,
    h: float,
    label: str,
    *,
    tone: str = "ghost",
    dashed: bool = True,
) -> str:
    _, stroke, _ = TONES[tone](p)
    dash = ' stroke-dasharray="6 5"' if dashed else ""
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="none" '
        f'stroke="{stroke}" stroke-width="1.25"{dash}/>\n'
        f'<text x="{x + 14}" y="{y + 19}" font-size="11" font-weight="600" '
        f'letter-spacing="0.6" fill="{p.muted}">{escape(label.upper())}</text>'
    )


def arrow(
    p: Palette,
    points: list[tuple[float, float]],
    label: str = "",
    *,
    tone: str = "muted",
    dashed: bool = False,
    label_dx: float = 0,
    label_dy: float = -7,
) -> str:
    colour = {"muted": p.muted, "accent": p.accent, "danger": p.danger}[tone]
    marker = {"muted": "arrow", "accent": "arrow-accent", "danger": "arrow-danger"}[tone]
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    path = " ".join(
        ("M" if index == 0 else "L") + f" {x} {y}" for index, (x, y) in enumerate(points)
    )
    markup = (
        f'<path d="{path}" fill="none" stroke="{colour}" stroke-width="1.6"{dash} '
        f'marker-end="url(#{marker})"/>'
    )
    if label:
        mid = points[len(points) // 2]
        start = points[len(points) // 2 - 1]
        mx, my = (mid[0] + start[0]) / 2, (mid[1] + start[1]) / 2
        markup += (
            f'\n<text x="{mx + label_dx}" y="{my + label_dy}" text-anchor="middle" '
            f'font-size="11" fill="{p.muted}">{escape(label)}</text>'
        )
    return markup


def caption(
    p: Palette,
    x: float,
    y: float,
    text: str,
    *,
    anchor: str = "start",
    size: float = 11.5,
    muted: bool = True,
    mono: bool = False,
) -> str:
    family = f' font-family="{MONO}"' if mono else ""
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" '
        f'fill="{p.muted if muted else p.text}"{family}>{escape(text)}</text>'
    )


def heading(p: Palette, x: float, y: float, text: str) -> str:
    return (
        f'<text x="{x}" y="{y}" font-size="12" font-weight="700" letter-spacing="0.7" '
        f'fill="{p.muted}">{escape(text.upper())}</text>'
    )


# ── Diagram 1: architecture ──────────────────────────────────────────────────


def architecture(p: Palette) -> Canvas:
    c = Canvas(1000, 620)

    c.add(heading(p, 32, 34, "AI Operations Agent — system architecture"))
    c.add(
        caption(
            p, 32, 54, "Everything the agent can reach, and what stands between it and each system."
        )
    )

    c.add(box(p, 32, 78, 190, 54, "Engineer", "natural-language task", tone="accent"))
    c.add(arrow(p, [(127, 132), (127, 168)]))

    # API layer
    c.add(region(p, 32, 168, 390, 120, "FastAPI"))
    c.add(box(p, 48, 196, 172, 34, "POST /runs", mono=True, radius=6))
    c.add(box(p, 48, 238, 172, 34, "POST /approval", mono=True, radius=6, tone="attention"))
    c.add(box(p, 234, 196, 172, 34, "GET /runs/{id}/trace", mono=True, radius=6))
    c.add(box(p, 234, 238, 172, 34, "GET /metrics", mono=True, radius=6))

    # Agent core
    c.add(region(p, 32, 308, 390, 168, "LangGraph workflow"))
    c.add(box(p, 48, 336, 172, 46, "State", "typed, checkpointed", tone="neutral"))
    c.add(box(p, 234, 336, 172, 46, "Guardrails", "budgets · allowlist · r/w"))
    c.add(
        box(
            p,
            48,
            396,
            172,
            60,
            "Planner",
            "chooses the next tool\nfrom the allowed set",
            tone="accent",
        )
    )
    c.add(
        box(
            p,
            234,
            396,
            172,
            60,
            "Approval gate",
            "pauses for a human\nbefore any write",
            tone="attention",
        )
    )

    # LLM
    c.add(
        box(
            p,
            32,
            502,
            390,
            56,
            "LLM  ·  LangChain",
            "optional — absent, the agent runs its deterministic path",
            tone="ghost",
            dashed=True,
        )
    )
    c.add(arrow(p, [(227, 476), (227, 502)], dashed=True))

    c.add(arrow(p, [(227, 288), (227, 308)], tone="accent"))

    # MCP boundary
    c.add(arrow(p, [(422, 392), (486, 392)], "MCP", tone="accent"))
    c.add(region(p, 486, 168, 482, 308, "MCP integration layer"))
    c.add(
        box(
            p,
            504,
            200,
            446,
            44,
            "MCP client pool",
            "discovers tools · read/write from annotations · degrades per server",
            tone="accent",
        )
    )

    servers = [
        ("monitoring", "metrics · alerts\naggregated errors", "success"),
        ("code", "deployments\ncommits · PRs", "success"),
        ("incident", "issues\ncreate · comment", "danger"),
        ("knowledge", "runbooks\nretrieval", "success"),
    ]
    for index, (name, detail, tone) in enumerate(servers):
        x = 504 + index * 113
        c.add(box(p, x, 274, 103, 70, name, detail, tone=tone, mono=True))
        c.add(arrow(p, [(x + 51, 244), (x + 51, 274)]))
        c.add(box(p, x, 372, 103, 44, "external", "system", tone="ghost", dashed=True))
        c.add(arrow(p, [(x + 51, 344), (x + 51, 372)], dashed=True))

    c.add(
        caption(
            p, 727, 444, "each server is its own process, speaking MCP over stdio", anchor="middle"
        )
    )

    # Storage and observability
    c.add(region(p, 486, 496, 482, 96, "State and telemetry"))
    c.add(box(p, 504, 524, 140, 50, "PostgreSQL", "runs · approvals\naudit · checkpoints"))
    c.add(box(p, 656, 524, 140, 50, "Prometheus", "run cost\nwrite safety"))
    c.add(box(p, 808, 524, 142, 50, "Grafana", "dashboard\nand alerts"))
    c.add(arrow(p, [(422, 254), (486, 254)], "", tone="muted"))
    c.add(arrow(p, [(422, 520), (486, 540)]))

    return c


# ── Diagram 2: the workflow graph ────────────────────────────────────────────


def workflow(p: Palette) -> Canvas:
    c = Canvas(1000, 700)

    c.add(heading(p, 32, 34, "The investigation graph"))
    c.add(
        caption(p, 32, 54, "Deterministic work first, then a bounded agentic loop, then a human.")
    )

    w, h = 224, 50
    main = 300  # left column: the investigation
    right = 676  # right column: conclusion and action
    mid_l, mid_r = main + w / 2, right + w / 2

    def node(x, y, title, subtitle="", tone="neutral"):
        c.add(box(p, x, y, w, h, title, subtitle, tone=tone, mono=True))

    # ── Left column ─────────────────────────────────────────────────────────
    c.add(box(p, mid_l - 38, 82, 76, 28, "START", tone="ghost", radius=14))
    c.add(arrow(p, [(mid_l, 110), (mid_l, 132)]))

    node(main, 132, "analyze_task", "service and time window")
    c.add(arrow(p, [(mid_l, 182), (mid_l, 206)]))

    node(main, 206, "collect_initial_context", "metrics · deploys · errors · alerts")
    c.add(arrow(p, [(main - 4, 231), (main - 76, 231)], tone="danger"))
    c.add(caption(p, main - 40, 222, "no signal", anchor="middle", size=10.5))
    c.add(
        box(
            p,
            24,
            206,
            200,
            50,
            "insufficient_context",
            "stops, and says why",
            tone="danger",
            mono=True,
        )
    )
    c.add(arrow(p, [(mid_l, 256), (mid_l, 280)]))

    node(main, 280, "correlate", "spike ↔ deployment ↔ commit", tone="success")
    c.add(arrow(p, [(mid_l, 330), (mid_l, 362)]))

    # ── The loop ────────────────────────────────────────────────────────────
    c.add(region(p, main - 116, 352, w + 148, 264, "agentic loop — bounded"))
    node(main, 382, "select_tool", "the model's one real choice", tone="accent")
    c.add(arrow(p, [(mid_l, 432), (mid_l, 458)]))
    node(main, 458, "execute_tool", "validated · timed · recorded")
    c.add(arrow(p, [(mid_l, 508), (mid_l, 534)]))
    node(main, 534, "evaluate_observation", "did that change anything?")

    c.add(
        arrow(
            p,
            [(main, 559), (main - 92, 559), (main - 92, 407), (main, 407)],
            "more to learn",
            tone="accent",
            label_dx=-52,
            label_dy=4,
        )
    )
    c.add(
        caption(
            p,
            main - 104,
            604,
            "exits on: nothing asked · budget spent · no progress · 4 iterations",
            size=10.5,
        )
    )

    # ── Right column, read bottom to top ────────────────────────────────────
    c.add(arrow(p, [(main + w, 559), (right + 14, 559)], "enough", label_dy=-9))
    node(right, 534, "generate_analysis", "structured · grounded", tone="success")
    c.add(arrow(p, [(mid_r, 534), (mid_r, 504)]))

    node(right, 454, "propose_action", "confidence ≥ 0.6, or nothing")
    c.add(arrow(p, [(mid_r, 454), (mid_r, 424)], tone="danger"))
    c.add(caption(p, mid_r + 10, 443, "write proposed", size=10.5))
    c.add(
        arrow(
            p,
            [(right, 479), (right - 40, 479), (right - 40, 190), (right + 4, 190)],
            "",
            tone="muted",
        )
    )
    c.add(caption(p, right - 50, 300, "nothing to write", anchor="end", size=10.5))

    node(right, 374, "request_approval", "graph pauses · state checkpointed", tone="attention")
    c.add(arrow(p, [(mid_r, 374), (mid_r, 344)], tone="danger"))
    c.add(caption(p, mid_r + 10, 363, "approved", size=10.5))
    c.add(
        arrow(
            p,
            [(right + w, 399), (right + w + 40, 399), (right + w + 40, 190), (right + w - 4, 190)],
            "",
        )
    )
    c.add(caption(p, right + w + 50, 300, "rejected", size=10.5))

    node(right, 294, "execute_action", "one tool · one step", tone="danger")
    c.add(arrow(p, [(mid_r, 294), (mid_r, 240)]))

    node(right, 190, "final_response", "says what it did, and did not, do")
    c.add(arrow(p, [(mid_r, 190), (mid_r, 164)]))
    c.add(box(p, mid_r - 32, 136, 64, 28, "END", tone="ghost", radius=14))

    # ── The gate, spelled out ───────────────────────────────────────────────
    c.add(box(p, 32, 634, 936, 48, "", "", tone="attention", radius=10))
    c.add(
        caption(
            p,
            52,
            656,
            "The pause is durable. State is checkpointed, so the decision arrives as a "
            "separate HTTP request from a separate person —",
            muted=False,
            size=12,
        )
    )
    c.add(
        caption(
            p,
            52,
            673,
            "and the action executed is the one the graph saved, not anything the "
            "approving request carries.",
            size=11.5,
        )
    )
    return c


# ── Diagram 3: what stops the agent ──────────────────────────────────────────


def guardrails(p: Palette) -> Canvas:
    c = Canvas(1000, 430)

    c.add(heading(p, 32, 34, "What the agent cannot do"))
    c.add(
        caption(
            p,
            32,
            54,
            "Every limit below is enforced in code, before a tool runs. "
            "None of it is a prompt instruction.",
        )
    )

    lanes = [
        (
            "The model proposes",
            "accent",
            [
                "sees only the tools the policy allows",
                "answers with a name and arguments",
                "cannot add a tool or widen its own reach",
            ],
        ),
        (
            "The registry decides",
            "neutral",
            [
                "unknown name → refused and recorded",
                "arguments validated against a schema",
                "identical call repeated → refused",
                "timeout and retry belong to the runtime",
            ],
        ),
        (
            "A person authorises",
            "attention",
            [
                "write tools are invisible to the planner",
                "the graph pauses; state is checkpointed",
                "the decision carries no action of its own",
                "permission is granted for one step",
            ],
        ),
    ]

    for index, (title, tone, points) in enumerate(lanes):
        x = 32 + index * 313
        c.add(box(p, x, 84, 292, 40, title, tone=tone))
        for line, text in enumerate(points):
            y = 148 + line * 30
            c.add(f'<circle cx="{x + 18}" cy="{y - 4}" r="3" fill="{TONES[tone](p)[1]}"/>')
            c.add(caption(p, x + 32, y, text, muted=False, size=12))

    c.add(arrow(p, [(324, 104), (345, 104)], tone="accent"))
    c.add(arrow(p, [(637, 104), (658, 104)], tone="accent"))

    c.add(box(p, 32, 300, 936, 44, "", "", tone="danger", radius=10))
    c.add(
        caption(
            p,
            52,
            327,
            "agent_unapproved_writes_total must stay at zero. It is derived from the recorded "
            "calls, not from a flag, and pages immediately if it ever moves.",
            muted=False,
            size=12.5,
        )
    )
    c.add(
        caption(
            p,
            32,
            380,
            "Budgets: 12 tool calls · 30 workflow steps · 4 loop iterations · 15 s per tool · "
            "2 identical calls · no shell, no code execution, no tool outside the registry.",
            size=12,
        )
    )
    return c


DIAGRAMS = {
    "architecture": (
        architecture,
        "AI Operations Agent architecture",
        "The agent sits behind a FastAPI service and reaches four external systems "
        "through MCP servers, with PostgreSQL for state and Prometheus for telemetry.",
    ),
    "workflow": (
        workflow,
        "The investigation graph",
        "A LangGraph workflow: deterministic collection and correlation, then a bounded "
        "loop of tool selection, then a human approval gate before any write.",
    ),
    "guardrails": (
        guardrails,
        "What the agent cannot do",
        "Three layers of enforcement: the model proposes, the registry validates and "
        "refuses, and a person authorises every write.",
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs/assets"),
        help="Directory to write the SVG files into.",
    )
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    for name, (build, title, description) in DIAGRAMS.items():
        for palette in (LIGHT, DARK):
            svg = build(palette).render(palette, title=title, description=description)
            path = args.out / f"{name}-{palette.name}.svg"
            path.write_text(svg, encoding="utf-8")
            print(f"wrote {path}")


if __name__ == "__main__":
    main()
