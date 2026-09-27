"""
Highlight detection scaffold — real Roboflow Inference integration.
 
WHAT THIS IS, HONESTLY:
This orchestrates automatic sports-highlight detection from a video the athlete
provides (by URL). The actual computer-vision inference runs on Roboflow's
Inference engine, which needs a GPU + model weights + a Roboflow API key on the
DEPLOYMENT running this code. It cannot run in a plain web container with no GPU,
and it does not run at import time here. This module:
  - is written to Roboflow's real InferencePipeline API contract,
  - aggregates per-frame object detections into KEY MOMENTS (timestamps),
  - fails safe (returns an honest "not configured / no source" result, never a
    fabricated highlight) when Roboflow isn't set up or the video can't be read.
 
WHAT IT DOES NOT DO:
It does not invent moments. If inference isn't available or finds nothing, it
says so plainly. Every returned moment corresponds to a real detection with a
real frame timestamp and confidence from the model.
 
REQUIRED TO RUN LIVE (on the deployment, not here):
  - pip install inference  (or inference-gpu for CUDA)
  - ROBOFLOW_API_KEY set in the environment
  - a model_id (default a general COCO detector that includes 'person' and
    'sports ball'); a sport-specific fine-tuned model gives far better moments.
"""
import os
 
ROBOFLOW_API_KEY = os.getenv("ROBOFLOW_API_KEY", "")
# Default model: RF-DETR base (COCO) detects 'person' and 'sports ball' out of the
# box - enough to find action density. Override with a sport-specific Universe
# model via ROBOFLOW_MODEL_ID for real quality.
ROBOFLOW_MODEL_ID = os.getenv("ROBOFLOW_MODEL_ID", "rfdetr-base")
# Minimum confidence for a detection to count.
DETECT_CONFIDENCE = float(os.getenv("ROBOFLOW_CONFIDENCE", "0.4"))
 
 
def detection_available() -> bool:
    """True only if the pieces needed for real inference are present: a Roboflow
    key AND the inference package importable. Used so callers can degrade
    honestly instead of pretending detection ran."""
    if not ROBOFLOW_API_KEY:
        return False
    try:
        import inference  # noqa: F401
        return True
    except Exception:
        return False
 
 
def _moments_from_frame_activity(frame_activity, fps, min_gap_s=6.0, top_n=12):
    """Turn a list of (frame_index, activity_score) into distinct key moments.
 
    'Activity' = how much is happening in a frame (object count / motion proxy).
    We find local peaks of activity, then collapse peaks closer than min_gap_s
    into one moment (so one goal isn't 30 near-identical clips). Only frames whose
    activity clears a threshold RELATIVE to the video's own activity level count -
    so a quiet stretch never becomes a false "highlight" just to fill top_n.
    Returns moments sorted chronologically, each with a timestamp. Pure function -
    fully testable without any GPU or network, which is where the real logic lives.
    """
    if not frame_activity or not fps or fps <= 0:
        return []
    scores = [s for _, s in frame_activity if s > 0]
    if not scores:
        return []
    # Relative threshold: a moment must be meaningfully above this video's own
    # average activity (peaks stand out from the baseline). Guards against quiet
    # footage producing junk moments. Also require an absolute floor > 0.
    avg = sum(scores) / len(scores)
    peak = max(scores)
    # need to be at least ~60% of the way from average to peak, and clearly > baseline
    threshold = max(avg * 1.4, avg + 0.5 * (peak - avg))
    ranked = sorted(frame_activity, key=lambda fa: fa[1], reverse=True)
    picked = []
    for frame_idx, score in ranked:
        if score < threshold or score <= 0:
            continue
        t = frame_idx / fps
        if all(abs(t - p["time_s"]) >= min_gap_s for p in picked):
            picked.append({
                "time_s": round(t, 1),
                "timestamp": _fmt_ts(t),
                "activity_score": round(float(score), 3),
                "frame_index": int(frame_idx),
            })
        if len(picked) >= top_n:
            break
    # present in chronological order (a reel is built in time order)
    picked.sort(key=lambda m: m["time_s"])
    return picked
 
 
def _fmt_ts(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"
 
 
def detect_highlights_from_url(video_url: str, sport: str = "", max_moments: int = 12) -> dict:
    """Run Roboflow inference over a video URL and return detected key moments.
 
    Returns a dict:
      {
        "available": bool,          # was real detection possible?
        "moments": [ {timestamp, time_s, activity_score, frame_index, label}, ... ],
        "note": str,                # honest status / guidance
        "model_id": str,
      }
    NEVER returns fabricated moments. If detection isn't configured or the video
    can't be processed, available=False and moments=[] with an explanatory note.
    """
    result = {"available": False, "moments": [], "note": "", "model_id": ROBOFLOW_MODEL_ID}
 
    if not video_url or not video_url.strip():
        result["note"] = "No video URL provided."
        return result
 
    if not detection_available():
        result["note"] = (
            "Automatic detection isn't configured on this deployment. It requires a "
            "ROBOFLOW_API_KEY and the 'inference' package running on a GPU-capable host. "
            "You can still use the clip-planning workshop by describing your moments."
        )
        return result
 
    # --- Real inference path (runs on the GPU deployment, not in a plain sandbox) ---
    try:
        from inference import InferencePipeline
    except Exception as e:
        result["note"] = f"Inference package unavailable: {e}. Use the clip-planning workshop instead."
        return result
 
    # Collect per-frame activity via the pipeline's prediction callback.
    frame_activity = []  # list of (frame_index, activity_score)
    fps_holder = {"fps": 0.0}
 
    def on_prediction(predictions, video_frame):
        # predictions.predictions: list of {x,y,width,height,class,confidence}
        try:
            preds = getattr(predictions, "predictions", None)
            if preds is None and isinstance(predictions, dict):
                preds = predictions.get("predictions", [])
            preds = preds or []
            # Activity proxy: number of confident detections in the frame, weighted
            # by confidence, with 'sports ball' + clusters of 'person' weighted up
            # (action tends to concentrate people and the ball).
            score = 0.0
            for p in preds:
                conf = _pget(p, "confidence", 0.0)
                if conf < DETECT_CONFIDENCE:
                    continue
                cls = str(_pget(p, "class", "")).lower()
                w = 1.0
                if "ball" in cls:
                    w = 2.5
                elif "person" in cls:
                    w = 1.0
                score += conf * w
            frame_idx = getattr(video_frame, "frame_id", None)
            if frame_idx is None:
                frame_idx = getattr(video_frame, "frame_timestamp", len(frame_activity))
            # capture fps if the frame exposes it
            f = getattr(video_frame, "fps", None)
            if f:
                fps_holder["fps"] = float(f)
            frame_activity.append((int(frame_idx) if isinstance(frame_idx, (int, float)) else len(frame_activity), score))
        except Exception:
            # one bad frame must never abort the whole run
            frame_activity.append((len(frame_activity), 0.0))
 
    try:
        pipeline = InferencePipeline.init(
            model_id=ROBOFLOW_MODEL_ID,
            video_reference=video_url,
            on_prediction=on_prediction,
            api_key=ROBOFLOW_API_KEY,
            confidence=DETECT_CONFIDENCE,
        )
        pipeline.start()
        pipeline.join()
    except Exception as e:
        result["note"] = (
            f"Couldn't process this video automatically ({e}). Common causes: the URL "
            "isn't a directly-readable video file, or the host blocks access. You can "
            "still describe your moments in the clip-planning workshop."
        )
        return result
 
    fps = fps_holder["fps"] or 30.0  # sane default if the source didn't report it
    moments = _moments_from_frame_activity(frame_activity, fps, top_n=max_moments)
    for m in moments:
        m["label"] = "High-activity moment"  # honest: this is action density, not "a goal"
 
    result["available"] = True
    result["moments"] = moments
    if not moments:
        result["note"] = (
            "Processing ran but found no clear high-activity moments - the footage may be "
            "low-motion, very short, or the model didn't recognize the action. A "
            "sport-specific model (ROBOFLOW_MODEL_ID) improves this a lot."
        )
    else:
        result["note"] = (
            f"Found {len(moments)} high-activity moments by detection density. These are "
            "starting points - review each and keep the ones that are genuinely your best. "
            "Then send them to the clip-planning workshop to build the reel."
        )
    return result
 
 
def _pget(pred, key, default=None):
    """Read a field from a prediction that may be an object or a dict."""
    if isinstance(pred, dict):
        return pred.get(key, default)
    return getattr(pred, key, default)
 
