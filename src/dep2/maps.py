"""Map rendering with the required cartographic elements (title, legend, north arrow, scale bar,
CRS, source, reference period, NoData representation, boundary, evidence-type label)."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

NODATA_COLOR = "#d9d9d9"


def base_axes(title, subtitle):
    fig, ax = plt.subplots(figsize=(8.3, 10.2), dpi=150)
    ax.set_title(title, fontsize=13, loc="left", fontweight="bold", pad=30)
    import textwrap
    ax.text(0, 1.005, "\n".join(textwrap.wrap(subtitle, 105)), transform=ax.transAxes, fontsize=8.2, va="bottom", color="#333")
    ax.set_axis_off()
    return fig, ax


EXTENT = None  # set by the runner to the ward bounds (+ margin) so stray features never rescale a map


def furniture(ax, source, period, evidence_type, crs="EPSG:32644 (WGS 84 / UTM 44N)", extra_legend=None, legend_title=None, legend_loc="lower left"):
    if EXTENT is not None:
        ax.set_xlim(EXTENT[0], EXTENT[2])
        ax.set_ylim(EXTENT[1], EXTENT[3])
        ax.set_aspect("equal")
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    # north arrow
    ax.annotate("N", xy=(0.94, 0.95), xytext=(0.94, 0.88), xycoords="axes fraction", ha="center", va="center", fontsize=12, fontweight="bold",
                arrowprops=dict(arrowstyle="-|>", color="black", lw=1.5))
    # scale bar (5 km)
    L = 5000
    sx, sy = x0 + 0.05 * (x1 - x0), y0 + 0.03 * (y1 - y0)
    ax.plot([sx, sx + L], [sy, sy], color="black", lw=3, solid_capstyle="butt")
    ax.plot([sx, sx + L / 2], [sy, sy], color="white", lw=1.5, solid_capstyle="butt")
    ax.text(sx, sy + 0.012 * (y1 - y0), "0", fontsize=7, ha="center")
    ax.text(sx + L, sy + 0.012 * (y1 - y0), "5 km", fontsize=7, ha="center")
    if extra_legend:
        ax.legend(handles=extra_legend, title=legend_title, loc=legend_loc, fontsize=7.5, title_fontsize=8, frameon=True, framealpha=0.9,
                  bbox_to_anchor=(0.0, 0.06) if legend_loc == "lower left" else None)
    import textwrap
    txt = f"Evidence type: {evidence_type}\nReference period: {period}\nCRS: {crs}\n" + "\n".join(textwrap.wrap("Source: " + source, 150))
    ax.figure.text(0.02, 0.01, txt, fontsize=6.8, va="bottom", ha="left", wrap=True)


def nodata_patch(label="NoData / not assessed (never zero)"):
    return Patch(facecolor=NODATA_COLOR, edgecolor="#999", label=label)


def save(fig, path: Path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.subplots_adjust(left=0.02, right=0.98, top=0.93, bottom=0.12)
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def choropleth(wards, col, title, subtitle, source, period, evidence_type, path, cmap="YlOrRd", fmt="{:.2f}", k=5, boundary=None, points=None, point_kw=None, point_label=None):
    """Quantile classes; wards with NaN are drawn in the NoData colour (never as the lowest class)."""
    import numpy as np
    fig, ax = base_axes(title, subtitle)
    v = wards[col].astype(float)
    ok = v.notna()
    handles = []
    if ok.any():
        qs = np.unique(np.nanquantile(v[ok], np.linspace(0, 1, k + 1)))
        base = plt.get_cmap(cmap)
        nq = max(len(qs) - 1, 1)
        cm = lambda i: base(0.2 + 0.8 * i / max(nq - 1, 1))  # noqa: E731  (never pure white: white is reserved for 'no data drawn')
        cls = np.clip(np.searchsorted(qs, v[ok], side="right") - 1, 0, len(qs) - 2)
        wards[ok].assign(_c=cls).plot(ax=ax, color=[cm(c) for c in cls], edgecolor="white", linewidth=0.3)
        for i in range(len(qs) - 1):
            handles.append(Patch(facecolor=cm(i), label=f"{fmt.format(qs[i])} – {fmt.format(qs[i + 1])}"))
    if (~ok).any():
        wards[~ok].plot(ax=ax, color=NODATA_COLOR, edgecolor="#999", linewidth=0.3, hatch="///")
        handles.append(nodata_patch())
    (boundary if boundary is not None else wards).boundary.plot(ax=ax, color="#444", linewidth=0.6)
    if points is not None and len(points):
        points.plot(ax=ax, **(point_kw or {"markersize": 4, "color": "black"}))
        from matplotlib.lines import Line2D
        handles.append(Line2D([], [], marker="o", ls="", color=(point_kw or {}).get("color", "black"), markersize=4, label=point_label or "points"))
    furniture(ax, source, period, evidence_type, extra_legend=handles, legend_title=col)
    return save(fig, path)
