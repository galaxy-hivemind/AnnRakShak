"""
AnnaRakshak — Camera Foundation Test
=====================================
Reliably opens the first available webcam on macOS (built-in FaceTime camera
or any connected USB camera), displays a live preview with an on-screen status
overlay, and exits cleanly when 'q' is pressed.

Camera selection
----------------
* By default the script scans indices 0-4 via AVFoundation and opens the first
  camera it finds.  On a MacBook Air with no external camera connected this is
  always the built-in FaceTime camera (index 0).
* When a USB camera (e.g. Logitech C505e) is also connected it typically
  appears at index 1 or higher.  Use --index to target it explicitly.
* Run 'system_profiler SPCameraDataType' to list all cameras macOS recognises.

Usage
-----
    source .venv/bin/activate
    python camera_test.py              # auto-detect first camera
    python camera_test.py --index 0    # built-in FaceTime camera (default)
    python camera_test.py --index 1    # first external USB camera
    python camera_test.py --list       # list cameras seen by macOS and exit

macOS Camera Permissions
------------------------
If you see "Could not open camera", go to:
    System Settings → Privacy & Security → Camera
and enable access for Terminal (or whichever app launches Python).
Quit and reopen Terminal after changing the setting.
"""

import argparse
import subprocess
import sys
import time

import cv2

# ── Constants ────────────────────────────────────────────────────────────────

WINDOW_TITLE = "AnnaRakshak — Camera Test"

# Resolution candidates to probe, from preferred to fallback.
# AVFoundation silently clamps to the nearest resolution the device supports.
# MacBook Air FaceTime camera native: 1920x1080; negotiates down to 1280x720.
# Logitech C505e native max: 1280x720.
RESOLUTION_CANDIDATES = [
    (1280, 720),   # HD  — works on both built-in and C505e
    (960, 540),    # qHD
    (640, 480),    # VGA — universal fallback
]

# Maximum camera index to scan when auto-detecting.
MAX_SCAN_INDEX = 4

# Status overlay colours (BGR)
COLOUR_OK    = (0, 220, 90)    # green
COLOUR_WARN  = (0, 165, 255)   # orange
COLOUR_ERROR = (0, 60, 220)    # red


# ── Camera helpers ────────────────────────────────────────────────────────────

def open_camera(index: int) -> cv2.VideoCapture | None:
    """
    Try to open a camera at *index* using AVFoundation (the native macOS
    backend).  Returns the VideoCapture object on success, None on failure.
    """
    # CAP_AVFOUNDATION is the native macOS backend — avoids CoreMedia warnings.
    cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    if cap.isOpened():
        return cap
    cap.release()
    return None


def probe_resolution(cap: cv2.VideoCapture) -> tuple[int, int]:
    """
    Request each resolution candidate in order and return whichever the
    driver actually accepts (confirmed by reading back the set values).
    """
    for w, h in RESOLUTION_CANDIDATES:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if actual_w > 0 and actual_h > 0:
            return actual_w, actual_h
    # Should never reach here, but be safe.
    return (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))


def list_system_cameras() -> list[str]:
    """
    Return a list of camera names that macOS reports via system_profiler.
    Runs quickly and requires no camera permission.  Returns an empty list
    if system_profiler is unavailable (non-macOS) or produces no output.
    """
    try:
        result = subprocess.run(
            ["system_profiler", "SPCameraDataType"],
            capture_output=True, text=True, timeout=5,
        )
        names = []
        for line in result.stdout.splitlines():
            stripped = line.strip()
            # system_profiler lists each camera as "Camera Name:" at indent 1
            if stripped.endswith(":") and not stripped.startswith("Camera:"):
                names.append(stripped.rstrip(":"))
        return names
    except Exception:
        return []


def find_first_camera() -> tuple[int, cv2.VideoCapture] | None:
    """
    Scan indices 0 … MAX_SCAN_INDEX and return (index, cap) for the first
    camera that opens successfully, or None if none is found.

    Also prints the cameras that macOS recognises so the user can cross-check
    which physical device each index corresponds to.
    """
    names = list_system_cameras()
    if names:
        print(f"[AnnaRakshak] macOS sees {len(names)} camera(s):")
        for n in names:
            print(f"[AnnaRakshak]   • {n}")
    else:
        print("[AnnaRakshak] (Could not query camera names via system_profiler)")

    print(f"[AnnaRakshak] Scanning indices 0–{MAX_SCAN_INDEX} via AVFoundation …")
    for idx in range(MAX_SCAN_INDEX + 1):
        cap = open_camera(idx)
        if cap is not None:
            print(f"[AnnaRakshak] Camera found at index {idx}.")
            return idx, cap
        print(f"[AnnaRakshak]   Index {idx}: not available.")
    return None


# ── Overlay rendering ─────────────────────────────────────────────────────────

def draw_overlay(frame, cam_index: int, width: int, height: int,
                 fps_actual: float, frame_count: int) -> None:
    """Render a semi-transparent status bar at the bottom of *frame*."""
    h, w = frame.shape[:2]
    bar_h = 36

    # Dark translucent strip
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, h - bar_h), (w, h), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

    status = (
        f"Camera #{cam_index}  |  {width}x{height}  |  "
        f"{fps_actual:.1f} fps  |  frame {frame_count}  |  [q] quit"
    )
    cv2.putText(
        frame, status,
        (10, h - 10),
        cv2.FONT_HERSHEY_SIMPLEX, 0.52, COLOUR_OK, 1, cv2.LINE_AA,
    )

    # Top-left branding
    cv2.putText(
        frame, "AnnaRakshak — Camera Test",
        (10, 24),
        cv2.FONT_HERSHEY_SIMPLEX, 0.65, COLOUR_OK, 2, cv2.LINE_AA,
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="AnnaRakshak — live webcam preview test."
    )
    parser.add_argument(
        "--index", type=int, default=None,
        help=("Camera index to use (default: auto-detect first available). "
              "Index 0 is usually the built-in FaceTime camera on a MacBook."),
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List cameras seen by macOS (system_profiler) and exit.",
    )
    args = parser.parse_args()

    if args.list:
        names = list_system_cameras()
        if names:
            print(f"Cameras visible to macOS ({len(names)} found):")
            for i, n in enumerate(names):
                print(f"  [{i}] {n}")
            print()
            print("Note: the index shown here may not match the OpenCV index.")
            print("Use --index 0, --index 1, etc. to try each one.")
        else:
            print("No cameras found by system_profiler (or not on macOS).")
        return 0

    # ── Open camera ──────────────────────────────────────────────────────────
    TROUBLESHOOT = (
        "\nTroubleshooting steps:\n"
        "  1. For the built-in camera: no cable needed — just grant permission below.\n"
        "  2. For a USB camera: check that it is firmly connected and powered.\n"
        "  3. Go to System Settings → Privacy & Security → Camera\n"
        "     and enable access for Terminal (or your IDE).\n"
        "     Quit and reopen Terminal after granting permission.\n"
        "  4. Close any app currently using the camera (FaceTime, Zoom, QuickTime).\n"
        "  5. Run: python camera_test.py --list    (to see what macOS detects)\n"
        "  6. Try each index: python camera_test.py --index 0   (or --index 1)\n"
    )

    if args.index is not None:
        print(f"[AnnaRakshak] Opening camera at index {args.index} …")
        cap = open_camera(args.index)
        if cap is None:
            print(f"\n[ERROR] Could not open camera at index {args.index}.\n")
            print(TROUBLESHOOT)
            return 1
        cam_index = args.index
    else:
        result = find_first_camera()
        if result is None:
            print(f"\n[ERROR] No camera found at any index (0–{MAX_SCAN_INDEX}).\n")
            print(TROUBLESHOOT)
            return 1
        cam_index, cap = result

    # ── Configure resolution ──────────────────────────────────────────────────
    width, height = probe_resolution(cap)
    print(f"[AnnaRakshak] Resolution set to {width}x{height}.")

    # Warm-up: read a few frames so the sensor stabilises.
    for _ in range(3):
        cap.read()

    # ── Preview loop ──────────────────────────────────────────────────────────
    print(f"[AnnaRakshak] Preview started. Press [q] in the window to quit.\n")

    frame_count   = 0
    fps_actual    = 0.0
    t_fps_start   = time.monotonic()
    fps_interval  = 30   # recalculate fps every N frames

    try:
        while True:
            ok, frame = cap.read()

            if not ok or frame is None:
                print("[AnnaRakshak] Warning: failed to read a frame — retrying …")
                time.sleep(0.05)
                continue

            frame_count += 1

            # FPS calculation
            if frame_count % fps_interval == 0:
                elapsed = time.monotonic() - t_fps_start
                fps_actual = fps_interval / elapsed if elapsed > 0 else 0.0
                t_fps_start = time.monotonic()

            draw_overlay(frame, cam_index, width, height, fps_actual, frame_count)
            cv2.imshow(WINDOW_TITLE, frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                print("[AnnaRakshak] 'q' pressed — exiting preview.")
                break

    except KeyboardInterrupt:
        print("\n[AnnaRakshak] Interrupted — exiting.")

    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("[AnnaRakshak] Camera released. Goodbye.")

    return 0


if __name__ == "__main__":
    sys.exit(main())