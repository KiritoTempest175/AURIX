#!/usr/bin/env python3
"""Measure real resource usage; no simulated values or hard resource guarantees.

Requires psutil. NVML metrics, if available, describe the entire GPU.
"""
from __future__ import annotations

import argparse
import csv
import statistics
import time
from pathlib import Path

import psutil


def process_tree(pid: int):
    parent = psutil.Process(pid)
    children = parent.children(recursive=True)
    return [parent] + children


def sample(pid: int):
    processes = []
    try:
        processes = process_tree(pid)
    except psutil.Error as exc:
        raise RuntimeError(f"Process {pid} unavailable: {exc}") from exc
    cpu = 0.0
    rss = 0
    for process in processes:
        try:
            cpu += process.cpu_percent(interval=None)
            rss += process.memory_info().rss
        except psutil.Error:
            pass
    gpu = None
    vram = None
    try:
        from pynvml import nvmlInit, nvmlDeviceGetHandleByIndex, nvmlDeviceGetUtilizationRates, nvmlDeviceGetMemoryInfo
        nvmlInit()
        handle = nvmlDeviceGetHandleByIndex(0)
        gpu = float(nvmlDeviceGetUtilizationRates(handle).gpu)
        vram = round(nvmlDeviceGetMemoryInfo(handle).used / (1024 ** 2), 1)
    except (ImportError, OSError, Exception):
        pass
    return {"timestamp": time.time(), "cpu_percent_tree": round(cpu, 2),
            "rss_mb_tree": round(rss / 1024**2, 2), "gpu_percent_system": gpu,
            "vram_mb_system": vram}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pid", type=int, required=True)
    p.add_argument("--seconds", type=int, default=60)
    p.add_argument("--interval", type=float, default=2.0)
    p.add_argument("--csv", type=Path, default=Path("resource-proof.csv"))
    a = p.parse_args()
    if a.seconds < 1 or a.interval <= 0:
        p.error("--seconds and --interval must be positive")
    try:
        for proc in process_tree(a.pid):
            proc.cpu_percent(interval=None)
    except psutil.Error as exc:
        p.error(str(exc))
    rows = []
    start = time.monotonic()
    try:
        while time.monotonic() - start < a.seconds:
            time.sleep(a.interval)
            rows.append(sample(a.pid))
    except KeyboardInterrupt:
        pass
    if not rows:
        p.error("No samples gathered")
    with a.csv.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    for key in ("cpu_percent_tree", "rss_mb_tree", "gpu_percent_system", "vram_mb_system"):
        values = [float(row[key]) for row in rows if row[key] is not None]
        if values:
            print(f"{key}: min={min(values):.2f} avg={statistics.mean(values):.2f} max={max(values):.2f}")
        else:
            print(f"{key}: unavailable")
    print(f"Captured {len(rows)} real samples to {a.csv}")
    print("GPU metrics are system-wide and cannot prove per-app VRAM caps.")


if __name__ == "__main__":
    main()
