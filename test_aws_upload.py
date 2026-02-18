"""
Quick test script for the AWS monitoring upload endpoint.
Bypasses the full 10-minute learning pipeline -- just hits the API directly.

Usage:
    python test_aws_upload.py --key YOUR_LICENSE_KEY
    python test_aws_upload.py --key YOUR_LICENSE_KEY --sensor-id MySensor01
    python test_aws_upload.py --key YOUR_LICENSE_KEY --csv path/to/real_sensor.csv
    python test_aws_upload.py --key YOUR_LICENSE_KEY --baseline path/to/baseline.json
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: 'requests' not installed. Run: pip install requests")
    sys.exit(1)


AWS_ENDPOINT = "https://smv4232qo6.execute-api.us-east-1.amazonaws.com/prod/uploads"


def make_dummy_baseline_json() -> dict:
    """Build a minimal but realistic baseline.json payload (v2 three-tier format)."""
    n_bins = 5  # truncated for testing
    return {
        "analyzer": {
            "fs": 104.0,
            "nperseg": 4096,
            "noverlap": 2048,
            "median_window": 51,
        },
        "p_fa": 0.01,
        "n_phase1_frames": 5,
        "n_phase2_frames": 5,
        "phase1_frozen": True,
        "calibrated": True,
        "freqs": [0.0, 0.5, 1.0, 1.5, 2.0],
        "axes": {
            "accel_x": {
                "psd_baseline": [-50.0, -48.0, -45.0, -43.0, -40.0],
                "dof_baseline": 10,
                "noise_floor": [-51.0, -49.0, -46.0, -44.0, -41.0],
                "prominence": [1.0, 1.0, 1.0, 1.0, 1.0],
                "process_var": [0.5, 0.6, 0.4, 0.55, 0.45],
                "floor_process_std": 0.3,
            },
            "accel_y": {
                "psd_baseline": [-52.0, -50.0, -47.0, -44.0, -42.0],
                "dof_baseline": 10,
                "noise_floor": [-53.0, -51.0, -48.0, -45.0, -43.0],
                "prominence": [1.1, 0.9, 1.0, 1.2, 1.0],
                "process_var": [0.55, 0.5, 0.45, 0.6, 0.5],
                "floor_process_std": 0.32,
            },
            "accel_z": {
                "psd_baseline": [-48.0, -46.0, -43.0, -41.0, -38.0],
                "dof_baseline": 10,
                "noise_floor": [-49.0, -47.0, -44.0, -42.0, -39.0],
                "prominence": [0.9, 1.1, 1.0, 0.8, 1.2],
                "process_var": [0.45, 0.55, 0.5, 0.4, 0.6],
                "floor_process_std": 0.28,
            },
        },
    }


def make_dummy_detection_result() -> dict:
    """Build a sample detection result (simulating an anomaly, three-tier format)."""
    return {
        "accel_x": {
            "floor_z": 2.8,
            "floor_p": 0.005,
            "floor_shift_db": 3.2,
            "shape_stat": 3.1,
            "shape_p": 0.002,
            "feature_stat": 1.5,
            "feature_p": 0.12,
            "triggered": True,
            "tier_triggered": ["floor", "shape"],
        },
        "accel_y": {
            "floor_z": 0.5,
            "floor_p": 0.62,
            "floor_shift_db": 0.3,
            "shape_stat": 1.1,
            "shape_p": 0.35,
            "feature_stat": 0.8,
            "feature_p": 0.45,
            "triggered": False,
            "tier_triggered": [],
        },
        "accel_z": {
            "floor_z": 3.5,
            "floor_p": 0.0004,
            "floor_shift_db": 5.1,
            "shape_stat": 2.8,
            "shape_p": 0.006,
            "feature_stat": 4.2,
            "feature_p": 0.001,
            "triggered": True,
            "tier_triggered": ["floor", "shape", "feature"],
        },
    }


def make_dummy_thresholds() -> dict:
    """Build sample thresholds dict (single p_fa, no per-axis thresholds)."""
    return {"p_fa": 0.01}


def make_dummy_detection_results_json() -> dict:
    """Build a sample detection_results.json payload (v2 three-tier format)."""
    return {
        "version": 2,
        "sensor_id": "test-sensor-001",
        "filename": "test_sensor_data.csv",
        "timestamp": "2026-02-12T16:00:00+00:00",
        "freqs": [float(i * 0.5) for i in range(20)],
        "axes": {
            "accel_x": {
                "new_psd_db": [-50.0 + i * 0.5 for i in range(20)],
                "z_scores": [0.1 * i for i in range(20)],
                "prominence_z": [0.05 * i for i in range(20)],
                "floor_z": 2.8,
                "floor_p": 0.005,
                "floor_shift_db": 3.2,
                "shape_stat": 3.1,
                "shape_p": 0.002,
                "feature_stat": 1.5,
                "feature_p": 0.12,
                "feature_freqs": [2.5, 5.0],
                "triggered": True,
                "tier_triggered": ["floor", "shape"],
                "top_deviations": [
                    {"freq_hz": 9.5, "z_score": 1.9},
                    {"freq_hz": 9.0, "z_score": 1.8},
                    {"freq_hz": 8.5, "z_score": 1.7},
                    {"freq_hz": 8.0, "z_score": 1.6},
                    {"freq_hz": 7.5, "z_score": 1.5},
                ],
            },
        },
    }


def make_dummy_csv() -> str:
    """Create a tiny dummy CSV and return its path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, prefix="test_sensor_"
    )
    tmp.write("Timestamp,accel_x,accel_y,accel_z\n")
    for i in range(100):
        tmp.write(f"{i * 9615},{0.01 * i},{-0.02 * i},{9.8 + 0.001 * i}\n")
    tmp.close()
    return tmp.name


def separator(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def test_upload(
    license_key: str,
    sensor_id: str,
    baseline_json: dict,
    csv_path: str,
    detection_result: dict,
    thresholds: dict,
    detection_results_json: dict = None,
) -> None:
    """Run the full upload flow step by step with clear output."""

    # ── Step 1: POST to get presigned URLs ──
    separator("STEP 1: Request presigned URLs")

    headers = {
        "auth-token": license_key,
        "evb-user-type": "customer",
    }
    # Build filenames list from what we're uploading
    csv_filename = Path(csv_path).name
    filenames = ["baseline.json", csv_filename]
    if detection_results_json:
        filenames.append("detection_results.json")

    payload = {
        "sensor_id": sensor_id,
        "filenames": filenames,
        "detection_result": detection_result,
        "thresholds": thresholds,
    }

    print(f"  Endpoint: {AWS_ENDPOINT}")
    print(f"  Headers:  auth-token = {license_key[:8]}...{license_key[-4:]}" if len(license_key) > 12 else f"  Headers:  auth-token = {license_key}")
    print(f"  Payload keys: {list(payload.keys())}")
    print()

    try:
        resp = requests.post(AWS_ENDPOINT, json=payload, headers=headers, timeout=15)
    except requests.exceptions.ConnectionError as e:
        print(f"  CONNECTION ERROR: {e}")
        print("  -> Check if the endpoint URL is correct")
        return
    except requests.exceptions.Timeout:
        print("  TIMEOUT: No response in 15 seconds")
        return

    print(f"  Status: {resp.status_code}")
    print(f"  Response headers: {dict(resp.headers)}")
    print()

    # Try to parse response
    try:
        resp_json = resp.json()
        print(f"  Response JSON:")
        print(f"  {json.dumps(resp_json, indent=4)}")
    except Exception:
        print(f"  Response body (raw): {resp.text[:500]}")

    if resp.status_code != 200:
        print(f"\n  FAILED at Step 1. Status {resp.status_code}.")
        print(f"  -> If 401/403: license key is invalid or expired")
        print(f"  -> If 400: request body format is wrong")
        print(f"  -> If 500: server-side error")
        return

    # ── Figure out the response shape ──
    separator("STEP 1.5: Analyzing response shape")

    # The response could be structured many ways. Let's detect it.
    urls = {}  # filename -> presigned URL

    if isinstance(resp_json, dict):
        # Option A: {"urls": {"baseline.json": "...", "sensor.csv": "..."}}
        # Option B: {"upload_urls": [{"filename": "...", "url": "..."}]}
        # Option C: {"baseline.json": "...", "sensor.csv": "..."}
        # Option D: {"baseline_url": "...", "data_url": "..."}
        # Option E: {"presigned_urls": {"baseline.json": "...", ...}}

        # Check for nested dict of URLs
        for wrapper_key in ["files", "urls", "upload_urls", "presigned_urls", "presigned"]:
            inner = resp_json.get(wrapper_key)
            if isinstance(inner, dict):
                # Dict mapping filename -> url
                for k, v in inner.items():
                    if isinstance(v, str) and ("amazonaws.com" in v or "s3." in v):
                        urls[k] = v
                        print(f"  Found URL: {wrapper_key}.{k}")
                break
            elif isinstance(inner, list):
                # List of {key/filename, url} objects
                for item in inner:
                    if isinstance(item, dict):
                        fn = item.get("key") or item.get("filename") or item.get("name")
                        url = item.get("url") or item.get("presigned_url") or item.get("upload_url")
                        if fn and url:
                            urls[fn] = url
                            print(f"  Found URL: {wrapper_key}[].{fn}")
                break

        # Fallback: check top-level keys
        if not urls:
            for k, v in resp_json.items():
                if isinstance(v, str) and ("amazonaws.com" in v or "s3." in v):
                    urls[k] = v
                    print(f"  Found URL at top-level key: '{k}'")

        # Fallback: known key names
        if not urls:
            for bkey in ["baseline_url", "baselineUrl"]:
                if bkey in resp_json:
                    urls["baseline.json"] = resp_json[bkey]
                    print(f"  Found baseline URL under key: '{bkey}'")
            for dkey in ["data_url", "dataUrl", "csv_url", "sensor_url"]:
                if dkey in resp_json:
                    urls[csv_filename] = resp_json[dkey]
                    print(f"  Found data URL under key: '{dkey}'")

    if not urls:
        print(f"  Could not find any presigned URLs in the response.")
        print(f"  Full response for debugging:")
        print(f"  {json.dumps(resp_json, indent=4)}")
        print(f"  -> Share this output with the backend person")
        return

    print(f"\n  Resolved {len(urls)} presigned URL(s): {list(urls.keys())}")

    # ── Step 2: Upload baseline.json ──
    separator("STEP 2: PUT baseline.json to presigned URL")

    # Keys come back as "sensor_id/filename", so match by suffix
    baseline_url = None
    for k, v in urls.items():
        if k.endswith("baseline.json"):
            baseline_url = v
            print(f"  Matched key: '{k}'")
            break
    if not baseline_url:
        print(f"  No presigned URL found for 'baseline.json'")
        print(f"  Available URL keys: {list(urls.keys())}")
        print(f"  -> Check if the backend expects a different filename")
    else:
        print(f"  URL: {baseline_url[:100]}...")
        baseline_body = json.dumps(baseline_json)
        print(f"  Uploading {len(baseline_body)} bytes of baseline JSON...")

        try:
            # No Content-Type header — presigned URL signature must match exactly
            put_resp = requests.put(
                baseline_url,
                data=baseline_body,
                timeout=30,
            )
            print(f"  Status: {put_resp.status_code}")
            if put_resp.status_code not in (200, 204):
                print(f"  Response: {put_resp.text[:300]}")
                print(f"  -> If 403: presigned URL may have expired or wrong content type")
            else:
                print(f"  SUCCESS")
        except Exception as e:
            print(f"  ERROR: {e}")

    # ── Step 3: Upload sensor CSV ──
    separator("STEP 3: PUT sensor CSV to presigned URL")

    # Keys come back as "sensor_id/filename", so match by suffix
    data_url = None
    for k, v in urls.items():
        if k.endswith(csv_filename):
            data_url = v
            print(f"  Matched key: '{k}'")
            break
    # Fallback: grab any non-baseline URL
    if not data_url:
        for k, v in urls.items():
            if not k.endswith("baseline.json"):
                data_url = v
                print(f"  Using URL keyed as '{k}' for CSV upload")
                break

    if not data_url:
        print(f"  No presigned URL found for CSV data")
        print(f"  Available URL keys: {list(urls.keys())}")
    else:
        csv_size = os.path.getsize(csv_path)
        print(f"  URL: {data_url[:100]}...")
        print(f"  Uploading {csv_path} ({csv_size / 1024:.1f} KB)...")

        try:
            # No Content-Type header — presigned URL signature must match exactly
            with open(csv_path, "rb") as f:
                put_resp = requests.put(
                    data_url,
                    data=f,
                    timeout=30,
                )
            print(f"  Status: {put_resp.status_code}")
            if put_resp.status_code not in (200, 204):
                print(f"  Response: {put_resp.text[:300]}")
            else:
                print(f"  SUCCESS")
        except Exception as e:
            print(f"  ERROR: {e}")

    # ── Step 4: Upload detection_results.json ──
    if detection_results_json:
        separator("STEP 4: PUT detection_results.json to presigned URL")

        det_url = None
        for k, v in urls.items():
            if k.endswith("detection_results.json"):
                det_url = v
                print(f"  Matched key: '{k}'")
                break

        if not det_url:
            print(f"  No presigned URL found for 'detection_results.json'")
            print(f"  Available URL keys: {list(urls.keys())}")
            print(f"  -> Backend may not support this file yet (upload skipped)")
        else:
            det_body = json.dumps(detection_results_json)
            print(f"  URL: {det_url[:100]}...")
            print(f"  Uploading {len(det_body)} bytes of detection results JSON...")

            try:
                put_resp = requests.put(det_url, data=det_body, timeout=30)
                print(f"  Status: {put_resp.status_code}")
                if put_resp.status_code not in (200, 204):
                    print(f"  Response: {put_resp.text[:300]}")
                else:
                    print(f"  SUCCESS")
            except Exception as e:
                print(f"  ERROR: {e}")

    # ── Summary ──
    separator("DONE")
    print("  If all steps returned 200/204, the upload flow works.")


def main():
    parser = argparse.ArgumentParser(
        description="Test AWS monitoring upload endpoint directly (no learning required)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--key", required=True, help="License key (auth-token)"
    )
    parser.add_argument(
        "--sensor-id", default="test-sensor-001", help="Sensor ID to use (default: test-sensor-001)"
    )
    parser.add_argument(
        "--csv", default=None, help="Path to a real sensor CSV to upload (otherwise uses dummy data)"
    )
    parser.add_argument(
        "--baseline", default=None, help="Path to a real baseline.json to upload (otherwise uses dummy data)"
    )
    parser.add_argument(
        "--endpoint", default=None, help="Override the AWS endpoint URL"
    )

    args = parser.parse_args()

    if args.endpoint:
        global AWS_ENDPOINT
        AWS_ENDPOINT = args.endpoint

    # Load or generate test data
    if args.baseline:
        print(f"Loading baseline from {args.baseline}")
        with open(args.baseline) as f:
            baseline_json = json.load(f)
    else:
        print("Using dummy baseline.json")
        baseline_json = make_dummy_baseline_json()

    if args.csv:
        csv_path = args.csv
        if not os.path.exists(csv_path):
            print(f"ERROR: CSV not found: {csv_path}")
            sys.exit(1)
        print(f"Using CSV: {csv_path}")
    else:
        csv_path = make_dummy_csv()
        print(f"Using dummy CSV: {csv_path}")

    detection_result = make_dummy_detection_result()
    thresholds = make_dummy_thresholds()
    detection_results_json = make_dummy_detection_results_json()

    print(f"\nSensor ID: {args.sensor_id}")

    test_upload(
        license_key=args.key,
        sensor_id=args.sensor_id,
        baseline_json=baseline_json,
        csv_path=csv_path,
        detection_result=detection_result,
        thresholds=thresholds,
        detection_results_json=detection_results_json,
    )

    # Clean up dummy CSV
    if not args.csv and os.path.exists(csv_path):
        os.unlink(csv_path)


if __name__ == "__main__":
    main()
