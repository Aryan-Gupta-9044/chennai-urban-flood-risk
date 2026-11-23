import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.patches import Patch


def _style(ax, title):
    ax.set_title(title, fontsize=11)
    ax.set_xlabel("Easting (m, EPSG:32644)")
    ax.set_ylabel("Northing (m)")
    ax.ticklabel_format(style="plain", useOffset=False)
    ax.tick_params(labelsize=7)


def raster_map(arr, grid, boundary_utm, title, path, nodata=None, cmap="viridis", label="",
               vmin=None, vmax=None, wards_utm=None):
    a = np.ma.masked_invalid(np.where(arr == nodata, np.nan, arr) if nodata is not None else arr)
    fig, ax = plt.subplots(figsize=(7, 7.5))
    im = ax.imshow(a, extent=grid.extent, cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest")
    if wards_utm is not None:
        wards_utm.boundary.plot(ax=ax, color="white", linewidth=0.3, alpha=0.6)
    boundary_utm.boundary.plot(ax=ax, color="black", linewidth=1.2)
    cb = fig.colorbar(im, ax=ax, shrink=0.75)
    cb.set_label(label)
    _style(ax, title)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def categorical_map(arr, grid, boundary_utm, classes, title, path):
    """classes: {code: (name, hex colour)}"""
    codes = sorted(classes)
    cmap = ListedColormap([classes[c][1] for c in codes])
    norm = BoundaryNorm([c - 0.5 for c in codes] + [codes[-1] + 0.5], cmap.N)
    a = np.ma.masked_where(~np.isin(arr, codes), arr)
    fig, ax = plt.subplots(figsize=(8, 7.5))
    ax.imshow(a, extent=grid.extent, cmap=cmap, norm=norm, interpolation="nearest")
    boundary_utm.boundary.plot(ax=ax, color="black", linewidth=1.2)
    present = [c for c in codes if (arr == c).any()]
    ax.legend(handles=[Patch(color=classes[c][1], label=classes[c][0]) for c in present],
              loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=8)
    _style(ax, title)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
