"""Where to point a tall frame on a wide clip, for its vertical version.

The models in assets/ are Ultralytics' yolo11n and yolo11n-pose, exported with
ultralytics 8.4.182 as YOLO("yolo11n.pt").export(format="onnx", imgsz=640,
opset=17, simplify=True). They are AGPL-3.0 licensed.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

from . import clips, mediainfo

log = logging.getLogger(__name__)

MODEL = os.path.join(os.path.dirname(__file__), "..", "assets", "yolo11n.onnx")
VERSION = 1
SAMPLES_PER_SECOND = 4
SAMPLE_WIDTH = 640
INPUT = 640
TALL = 9 / 16
CONFIDENCE = 0.35
# What each kind of thing is worth as a subject, by COCO class id.
WEIGHTS = {0: 1.0} | {k: 0.6 for k in range(14, 24)} | {k: 0.3 for k in range(1, 9)}
# A subject that moves less than this share of the frame's width over a shot
# is held still on; more and the frame follows it.
HOLD = 0.35
# The fastest a pan may go, in frame widths a second.
PAN_SPEED = 0.18
SCENE_THRESHOLD = 9
SHORTEST_SHOT = 0.5


def path_for(clip_id: int) -> str:
    return os.path.join(clips.CLIPS_DIR, f"{clip_id}.crop.json")


def cached(clip_id: int) -> dict | None:
    try:
        with open(path_for(clip_id), encoding="utf-8") as fh:
            found = json.load(fh)
    except (OSError, ValueError):
        return None
    return found if found.get("version") == VERSION else None


_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="smartcrop")
_pending: set[int] = set()
_lock = threading.Lock()


def ensure(clip_id: int) -> None:
    if cached(clip_id) is not None:
        return
    with _lock:
        if clip_id in _pending:
            return
        _pending.add(clip_id)
    _pool.submit(_run, clip_id)


def _run(clip_id: int) -> None:
    try:
        source = clips.video_path(clip_id)
        if not os.path.exists(source):
            return
        result = analyse(source, clips.picture(clip_id))
        target = path_for(clip_id)
        with open(target + ".part", "w", encoding="utf-8") as fh:
            json.dump(result, fh)
        os.replace(target + ".part", target)
    except Exception:  # noqa: BLE001 - a clip without a path plays centred
        log.exception("smart crop failed for clip %s", clip_id)
    finally:
        with _lock:
            _pending.discard(clip_id)


def remove(clip_id: int) -> None:
    try:
        os.remove(path_for(clip_id))
    except OSError:
        pass


_sessions: dict[str, object] = {}
POSE_MODEL = os.path.join(os.path.dirname(__file__), "..", "assets", "yolo11n-pose.onnx")


def _model(path: str):
    if path not in _sessions:
        import onnxruntime

        options = onnxruntime.SessionOptions()
        # Two threads, so the server stays quick while it works.
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        _sessions[path] = onnxruntime.InferenceSession(
            path, sess_options=options, providers=["CPUExecutionProvider"])
    return _sessions[path]


def _size(source: str) -> tuple[int, int, float]:
    out = subprocess.run(
        [mediainfo.FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:format=duration", "-of", "json", source],
        capture_output=True, text=True, timeout=30, check=True,
    ).stdout
    data = json.loads(out)
    stream = data["streams"][0]
    return int(stream["width"]), int(stream["height"]), float(data["format"]["duration"])


def _run_model(path: str, frame):
    import numpy as np

    height, width = frame.shape[:2]
    scale = INPUT / max(width, height)
    new_w, new_h = round(width * scale), round(height * scale)
    rows = (np.arange(new_h) / scale).astype(int).clip(0, height - 1)
    cols = (np.arange(new_w) / scale).astype(int).clip(0, width - 1)
    canvas = np.full((INPUT, INPUT, 3), 114, dtype=np.uint8)
    top, left = (INPUT - new_h) // 2, (INPUT - new_w) // 2
    canvas[top:top + new_h, left:left + new_w] = frame[rows][:, cols]
    blob = canvas.transpose(2, 0, 1)[None].astype(np.float32) / 255.0
    session = _model(path)
    output = session.run(None, {session.get_inputs()[0].name: blob})[0][0]

    def fx(v):
        return ((v - left) / scale / width).clip(0, 1)

    def fy(v):
        return ((v - top) / scale / height).clip(0, 1)

    return output, fx, fy


def _boxes(output, best, keep, fx, fy):
    import numpy as np

    cx, cy, w, h = output[0][keep], output[1][keep], output[2][keep], output[3][keep]
    return np.stack([fx(cx - w / 2), fy(cy - h / 2), fx(cx + w / 2), fy(cy + h / 2)], axis=1)


def people(frame) -> list[dict]:
    """Everybody in the frame, with where their head is (pose keypoints, not the box)."""
    import numpy as np

    output, fx, fy = _run_model(POSE_MODEL, frame)  # (56, 8400)
    confidence = output[4]
    keep = confidence >= CONFIDENCE
    if not keep.any():
        return []
    boxes = _boxes(output, confidence, keep, fx, fy)
    scores = confidence[keep]
    points = output[5:][:, keep].reshape(17, 3, -1)  # (keypoint, x/y/seen, person)
    found = []
    for index in _nms(boxes, scores, np.zeros(len(scores), dtype=int)):
        x1, y1, x2, y2 = (float(v) for v in boxes[index])
        xs = fx(points[:, 0, index])
        seen = points[:, 2, index] >= 0.5
        face = [float(xs[k]) for k in range(5) if seen[k]]
        shoulders = [float(xs[k]) for k in (5, 6) if seen[k]]
        if face:
            centre = sum(face) / len(face)
            half = max((max(face) - min(face)) * 0.9, (x2 - x1) * 0.12, 0.02)
        elif shoulders:
            centre = sum(shoulders) / len(shoulders)
            half = max((max(shoulders) - min(shoulders)) / 2, (x2 - x1) * 0.15, 0.02)
        else:
            centre, half = (x1 + x2) / 2, (x2 - x1) / 2
        found.append({"box": [x1, y1, x2, y2], "confidence": float(scores[index]), "kind": 0,
                      "focus": [max(0.0, centre - half), min(1.0, centre + half)]})
    return found


def things(frame) -> list[dict]:
    import numpy as np

    output, fx, fy = _run_model(MODEL, frame)  # (84, 8400)
    scores = output[4:]
    kinds = scores.argmax(axis=0)
    best = scores.max(axis=0)
    keep = (best >= CONFIDENCE) & np.isin(kinds, [k for k in WEIGHTS if k != 0])
    if not keep.any():
        return []
    boxes = _boxes(output, best, keep, fx, fy)
    found = []
    for index in _nms(boxes, best[keep], kinds[keep]):
        x1, y1, x2, y2 = (float(v) for v in boxes[index])
        found.append({"box": [x1, y1, x2, y2], "confidence": float(best[keep][index]),
                      "kind": int(kinds[keep][index]), "focus": [x1, x2]})
    return found


def detect(frame) -> list[dict]:
    return people(frame) or things(frame)


def _nms(boxes, scores, kinds, overlap: float = 0.5) -> list[int]:
    import numpy as np

    order = list(np.argsort(-scores))
    kept: list[int] = []
    while order:
        first = order.pop(0)
        kept.append(first)
        order = [other for other in order
                 if kinds[other] != kinds[first] or _iou(boxes[first], boxes[other]) < overlap]
    return kept


def _iou(a, b) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def look(source: str) -> tuple[list[float], list[tuple[float, list]], float, float]:
    """Returns (cuts, [(time, subjects)], aspect, duration)."""
    import numpy as np

    width, height, duration = _size(source)
    sample_h = round(SAMPLE_WIDTH * height / width / 2) * 2
    frame_bytes = SAMPLE_WIDTH * sample_h * 3
    graph = (
        f"[0:v]split=2[s][d];"
        f"[s]scale=256:-2,scdet=threshold={SCENE_THRESHOLD},nullsink;"
        f"[d]fps={SAMPLES_PER_SECOND},scale={SAMPLE_WIDTH}:{sample_h},format=rgb24[out]"
    )
    samples: list[tuple[float, list]] = []
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(
            ["nice", "-n", "10", mediainfo.FFMPEG, "-nostdin", "-hide_banner", "-threads", "2",
             "-i", source, "-an", "-filter_complex", graph, "-map", "[out]",
             "-f", "rawvideo", "pipe:1"],
            stdout=subprocess.PIPE, stderr=errors,
        )
        try:
            index = 0
            while True:
                raw = proc.stdout.read(frame_bytes)
                if len(raw) < frame_bytes:
                    break
                frame = np.frombuffer(raw, dtype=np.uint8).reshape(sample_h, SAMPLE_WIDTH, 3)
                samples.append((index / SAMPLES_PER_SECOND, detect(frame)))
                index += 1
        finally:
            proc.stdout.close()
            proc.wait(timeout=60)
        errors.seek(0)
        log_text = errors.read().decode("utf-8", "replace")
    cuts = [float(t) for t in re.findall(r"lavfi\.scd\.time: ([0-9.]+)", log_text)]
    return cuts, samples, width / height, duration


def _strength(subject: dict) -> float:
    x1, y1, x2, y2 = subject["box"]
    return WEIGHTS.get(subject["kind"], 0) * subject["confidence"] * (x2 - x1) * (y2 - y1)


def _centre(subject: dict) -> float:
    return (subject["focus"][0] + subject["focus"][1]) / 2


def lead(samples: list[tuple[float, list[dict]]], window: float) -> float | None:
    """Where the shot's main subject mostly is, chosen once per shot so a two-shot
    does not average into the gap between the faces.
    """
    groups: list[dict] = []
    for index, (_t, found) in enumerate(samples):
        for subject in sorted(found, key=_strength, reverse=True):
            x, weight = _centre(subject), _strength(subject)
            for group in groups:
                if abs(group["sum"] / group["weight"] - x) <= window * 0.4:
                    group["weight"] += weight
                    group["sum"] += weight * x
                    group["best"][index] = max(group["best"].get(index, 0.0), weight)
                    break
            else:
                groups.append({"weight": weight, "sum": weight * x, "best": {index: weight}})
    groups = [g for g in groups if g["weight"] > 0]
    if not groups:
        return None
    best = max(groups, key=lambda g: sum(g["best"].values()))
    return best["sum"] / best["weight"]


def target(subjects: list[dict], window: float, near: float | None = None) -> float | None:
    ranked = sorted(subjects, key=_strength, reverse=True)
    if near is not None:
        ranked = [s for s in ranked if abs(_centre(s) - near) <= window * 0.5] or []
    if not ranked:
        return None
    first = ranked[0]
    left, right = first["focus"]
    for other in sorted(subjects, key=_strength, reverse=True):
        if other is first or _strength(other) < 0.3 * _strength(first):
            continue
        wider_left, wider_right = min(left, other["focus"][0]), max(right, other["focus"][1])
        if wider_right - wider_left <= window * 0.95:
            left, right = wider_left, wider_right
    return (left + right) / 2


def _median(values: list[float], radius: int = 2) -> list[float]:
    out = []
    for i in range(len(values)):
        near = sorted(values[max(0, i - radius): i + radius + 1])
        out.append(near[len(near) // 2])
    return out


def _follow(times: list[float], xs: list[float]) -> list[float]:
    alpha = 0.35
    forward, backward = xs[:], xs[:]
    for i in range(1, len(xs)):
        forward[i] = forward[i - 1] + alpha * (xs[i] - forward[i - 1])
    for i in range(len(xs) - 2, -1, -1):
        backward[i] = backward[i + 1] + alpha * (xs[i] - backward[i + 1])
    smooth = [(a + b) / 2 for a, b in zip(forward, backward)]
    for i in range(1, len(smooth)):
        step = PAN_SPEED * (times[i] - times[i - 1])
        smooth[i] = min(max(smooth[i], smooth[i - 1] - step), smooth[i - 1] + step)
    return smooth


def plan(cuts: list[float], samples: list[tuple[float, list]], aspect: float,
         duration: float, picture: dict | None = None) -> dict:
    picture = picture or {"width": 1.0, "height": 1.0}
    window = min(1.0, TALL * picture["height"] / aspect)
    margin = (1 - picture["width"]) / 2
    low, high = margin + window / 2, 1 - margin - window / 2

    def clamp(x: float) -> float:
        return 0.5 if low > high else min(max(x, low), high)

    edges = [0.0]
    for cut in sorted(cuts):
        if cut - edges[-1] >= SHORTEST_SHOT and duration - cut >= SHORTEST_SHOT:
            edges.append(cut)
    edges.append(duration)

    shots = []
    previous = 0.5
    for start, end in zip(edges, edges[1:]):
        seen = [(t, found) for t, found in samples if start <= t < end]
        if not seen:
            nearest = min(samples, key=lambda pair: abs(pair[0] - (start + end) / 2), default=None)
            seen = [(start, nearest[1])] if nearest else []
        main = lead(seen, window)
        inside = [(t, target(found, window, main)) for t, found in seen]
        found = [(t, x) for t, x in inside if x is not None]
        if not found:
            # Nobody in it: the middle, unless the shot before had somebody.
            shots.append({"start": round(start, 3), "end": round(end, 3),
                          "points": [[round(start, 3), round(clamp(previous), 4)]]})
            continue
        times = [t for t, _ in inside]
        xs = []
        for t, x in inside:
            xs.append(x if x is not None else min(found, key=lambda p: abs(p[0] - t))[1])
        xs = _median(xs)
        if max(xs) - min(xs) <= HOLD * window:
            centre = clamp((max(xs) + min(xs)) / 2)
            points = [[round(start, 3), round(centre, 4)]]
        else:
            moved = _follow(times, xs)
            points = [[round(t, 3), round(clamp(x), 4)] for t, x in zip(times, moved)]
            points[0][0] = round(start, 3)
        previous = points[-1][1]
        shots.append({"start": round(start, 3), "end": round(end, 3), "points": points})
    return {"version": VERSION, "aspect": round(aspect, 4), "shots": shots}


def analyse(source: str, picture: dict | None = None) -> dict:
    cuts, samples, aspect, duration = look(source)
    return plan(cuts, samples, aspect, duration, picture)
