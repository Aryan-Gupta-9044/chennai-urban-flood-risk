"""Agreement between a detected flood raster and a REFERENCE product. This measures agreement with that product,
not 'accuracy': a reference derived from SAR, or digitised from a preliminary map, is itself uncertain."""
import numpy as np


def agreement(detected, reference, valid=None):
    d = np.asarray(detected) == 1
    r = np.asarray(reference) == 1
    v = np.ones(d.shape, bool) if valid is None else np.asarray(valid, bool)
    d, r = d & v, r & v
    tp, fp, fn = int((d & r).sum()), int((d & ~r).sum()), int((~d & r).sum())
    tn = int((v & ~d & ~r).sum())
    div = lambda a, b: float(a / b) if b else float("nan")
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "iou": div(tp, tp + fp + fn), "precision": div(tp, tp + fp),
            "recall": div(tp, tp + fn), "f1": div(2 * tp, 2 * tp + fp + fn),
            "note": "agreement with the reference product, not ground-truth accuracy"}
