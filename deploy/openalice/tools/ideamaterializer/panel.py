"""Read hash-bound, projected factor panels exposed by the materializer sandbox."""
import hashlib
import json
from pathlib import Path

import numpy as np


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_panel():
    spec = json.loads(Path("/data/scope.json").read_text())
    start, stop = spec["date_slice"]
    columns = spec["entity_indices"]
    arrays, reasons = [], []
    for field in spec["fields"]:
        pair = []
        for kind in ("values", "reason"):
            item = field[kind]
            if sha(item["path"]) != item["sha256"]:
                raise ValueError("Source hash differs: " + field["name"])
            a = np.load(item["path"], mmap_mode="r", allow_pickle=False)
            if a.shape != tuple(spec["shape"]):
                raise ValueError("Source axes differ")
            pair.append(np.array(a[start:stop, columns], order="C", copy=True))
        values, reason = pair
        if values.dtype != np.float64 or reason.dtype != np.uint8:
            raise ValueError("Source types differ")
        if not np.array_equal(np.isfinite(values), reason == 0):
            raise ValueError("Availability differs")
        arrays.append(values)
        reasons.append(reason)
    values = np.stack(arrays, axis=-1)
    reason = np.stack(reasons, axis=-1)
    values.setflags(write=False)
    reason.setflags(write=False)
    if sha("/data/axes.npz") != spec["axes_sha256"]:
        raise ValueError("Identity axes hash differs")
    with np.load("/data/axes.npz", allow_pickle=False) as axes:
        dates = axes["dates"][start:stop].copy()
        entities = axes["entity_ids"][columns].copy()
        membership = axes["observation_research_membership"][start:stop, columns].copy()
        resolved = axes["observation_research_resolved"][start:stop].copy()
        supported = axes["research_membership_domain_supported"][columns].copy()
    result = {"values": values, "reason": reason, "dates": dates, "entities": entities,
            "membership": membership, "membership_resolved": resolved, "domain_supported": supported,
            "formation_index": np.arange(start, stop), "fields": [f["name"] for f in spec["fields"]],
            "qualification": [f["qualification"] for f in spec["fields"]]}
    if spec.get("labels"):
        for kind, target in (("values", "labels"), ("reason", "label_reason"),
                             ("realization_index", "realization_index")):
            item = spec["labels"][kind]
            if sha(item["path"]) != item["sha256"]:
                raise ValueError("Label hash differs")
            a = np.load(item["path"], mmap_mode="r", allow_pickle=False)
            if a.shape != tuple(spec["shape"]):
                raise ValueError("Label axes differ")
            result[target] = np.array(a[start:stop, columns], order="C", copy=True)
            result[target].setflags(write=False)
        if (result["labels"].dtype != np.float64 or result["label_reason"].dtype != np.uint8
                or not np.issubdtype(result["realization_index"].dtype, np.integer)
                or not np.array_equal(np.isfinite(result["labels"]), result["label_reason"] == 0)):
            raise ValueError("Invalid label types or missingness")
        formation = np.arange(start, stop)[:, None]
        valid = np.isfinite(result["labels"])
        if np.any(valid & ((result["realization_index"] <= formation)
                         | (result["realization_index"] >= spec["shape"][0]))):
            raise ValueError("Invalid label realization clock")
        result["formation_index"] = np.arange(start, stop)
    return result
