"""
Script to generate the comprehensive AURIX Technical Architecture and Operation Guide PDF.
Builds a rich, publication-grade HTML document with embedded SVGs, diagrams, tables,
and code snippets, then renders it to a high-resolution PDF via headless Chrome/Edge.
"""

import os
import subprocess
import shutil

OUTPUT_PDF = os.path.abspath("AURIX_Comprehensive_System_Guide.pdf")
HTML_FILE = os.path.abspath("aurix_guide_temp.html")

html_content = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>AURIX — Comprehensive System Architecture & Technical Manual</title>
<style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=Space+Grotesk:wght@500;700&display=swap');

    @page {
        size: A4;
        margin: 18mm 16mm 20mm 16mm;
        @bottom-right {
            content: "Page " counter(page);
            font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
            font-size: 8pt;
            color: #64748b;
            font-weight: 600;
        }
        @bottom-left {
            content: "AURIX Technical Architecture & Operational Guide";
            font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
            font-size: 8pt;
            color: #94a3b8;
        }
    }

    * {
        box-sizing: border-box;
        margin: 0;
        padding: 0;
    }

    body {
        font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        color: #1e293b;
        background: #ffffff;
        line-height: 1.6;
        font-size: 10pt;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
    }

    .page-break {
        page-break-after: always;
        break-after: page;
    }

    .avoid-break {
        page-break-inside: avoid;
        break-inside: avoid;
    }

    /* Cover Page */
    .cover-page {
        height: 94vh;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        background: linear-gradient(135deg, #090d16 0%, #0f172a 50%, #1e1e38 100%);
        color: #ffffff;
        padding: 40px;
        border-radius: 12px;
        position: relative;
        overflow: hidden;
        border: 1px solid #334155;
    }

    .cover-badge {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        background: rgba(56, 189, 248, 0.15);
        border: 1px solid rgba(56, 189, 248, 0.4);
        color: #38bdf8;
        font-size: 9pt;
        font-weight: 700;
        letter-spacing: 1.5px;
        text-transform: uppercase;
        padding: 6px 14px;
        border-radius: 20px;
        width: fit-content;
    }

    .cover-title {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 38pt;
        font-weight: 700;
        letter-spacing: -1px;
        line-height: 1.1;
        background: linear-gradient(to right, #ffffff 30%, #38bdf8 70%, #818cf8 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-top: 20px;
        margin-bottom: 12px;
    }

    .cover-subtitle {
        font-size: 14pt;
        font-weight: 400;
        color: #94a3b8;
        max-width: 600px;
        line-height: 1.4;
        margin-bottom: 25px;
    }

    .cover-meta-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 15px;
        background: rgba(255, 255, 255, 0.04);
        border: 1px solid rgba(255, 255, 255, 0.08);
        padding: 16px;
        border-radius: 8px;
        backdrop-filter: blur(10px);
    }

    .cover-meta-item h4 {
        font-size: 7.5pt;
        text-transform: uppercase;
        color: #64748b;
        letter-spacing: 1px;
        margin-bottom: 4px;
    }

    .cover-meta-item p {
        font-size: 9.5pt;
        font-weight: 600;
        color: #f1f5f9;
    }

    .cover-footer {
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
        border-top: 1px solid rgba(255, 255, 255, 0.1);
        padding-top: 20px;
    }

    .cover-footer-text {
        font-size: 8.5pt;
        color: #64748b;
    }

    .cover-invariants {
        display: flex;
        gap: 10px;
        margin-top: 15px;
    }

    .inv-tag {
        background: rgba(16, 185, 129, 0.12);
        border: 1px solid rgba(16, 185, 129, 0.3);
        color: #34d399;
        font-size: 7.5pt;
        font-weight: 600;
        padding: 4px 10px;
        border-radius: 4px;
    }

    /* Headings */
    h1 {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 20pt;
        font-weight: 700;
        color: #0f172a;
        margin-top: 25px;
        margin-bottom: 12px;
        padding-bottom: 6px;
        border-bottom: 2px solid #e2e8f0;
        display: flex;
        align-items: center;
        gap: 10px;
    }

    h1 .section-num {
        background: #0284c7;
        color: #ffffff;
        font-size: 11pt;
        font-weight: 700;
        padding: 2px 8px;
        border-radius: 6px;
    }

    h2 {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 13.5pt;
        font-weight: 700;
        color: #1e293b;
        margin-top: 18px;
        margin-bottom: 8px;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    h3 {
        font-size: 11pt;
        font-weight: 700;
        color: #334155;
        margin-top: 12px;
        margin-bottom: 6px;
    }

    p {
        margin-bottom: 10px;
        color: #334155;
        text-align: justify;
    }

    /* Table of Contents */
    .toc-container {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 20px;
        margin-top: 15px;
        margin-bottom: 25px;
    }

    .toc-title {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 14pt;
        font-weight: 700;
        color: #0f172a;
        margin-bottom: 14px;
        padding-bottom: 6px;
        border-bottom: 1px solid #cbd5e1;
    }

    .toc-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 8px 24px;
    }

    .toc-item {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        font-size: 9pt;
        color: #334155;
        border-bottom: 1px dotted #cbd5e1;
        padding-bottom: 2px;
    }

    .toc-item .title {
        font-weight: 600;
        color: #0369a1;
    }

    .toc-item .desc {
        font-size: 8pt;
        color: #64748b;
    }

    /* Callouts & Alert Boxes */
    .callout {
        border-left: 4px solid #0284c7;
        background: #f0f9ff;
        padding: 12px 14px;
        border-radius: 0 6px 6px 0;
        margin: 12px 0;
        font-size: 9pt;
    }

    .callout-title {
        font-weight: 700;
        color: #0369a1;
        margin-bottom: 4px;
        display: flex;
        align-items: center;
        gap: 6px;
    }

    .callout-warning {
        border-left-color: #f59e0b;
        background: #fffbeb;
    }
    .callout-warning .callout-title { color: #b45309; }

    .callout-danger {
        border-left-color: #ef4444;
        background: #fef2f2;
    }
    .callout-danger .callout-title { color: #b91c1c; }

    .callout-success {
        border-left-color: #10b981;
        background: #ecfdf5;
    }
    .callout-success .callout-title { color: #047857; }

    /* Tables */
    table {
        width: 100%;
        border-collapse: collapse;
        margin: 12px 0 16px 0;
        font-size: 8.5pt;
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        overflow: hidden;
    }

    th {
        background: #f1f5f9;
        color: #0f172a;
        font-weight: 700;
        text-align: left;
        padding: 8px 10px;
        border-bottom: 2px solid #cbd5e1;
        font-size: 8.5pt;
    }

    td {
        padding: 7px 10px;
        border-bottom: 1px solid #f1f5f9;
        color: #334155;
        vertical-align: top;
    }

    tr:nth-child(even) {
        background: #f8fafc;
    }

    /* Code Blocks */
    pre, code {
        font-family: 'JetBrains Mono', Consolas, Monaco, monospace;
    }

    code {
        background: #f1f5f9;
        color: #0f172a;
        padding: 2px 5px;
        border-radius: 4px;
        font-size: 8.5pt;
        border: 1px solid #e2e8f0;
    }

    pre {
        background: #0f172a;
        color: #f8fafc;
        padding: 12px 14px;
        border-radius: 6px;
        font-size: 8pt;
        line-height: 1.45;
        overflow-x: auto;
        margin: 10px 0 14px 0;
        border: 1px solid #1e293b;
    }

    pre code {
        background: transparent;
        color: inherit;
        padding: 0;
        border: none;
        font-size: inherit;
    }

    .code-rust { border-left: 4px solid #f97316; }
    .code-py { border-left: 4px solid #3b82f6; }
    .code-slint { border-left: 4px solid #a855f7; }
    .code-sql { border-left: 4px solid #10b981; }

    /* Feature Grid / Cards */
    .card-grid-2 {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px;
        margin: 12px 0;
    }

    .card-grid-3 {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 10px;
        margin: 12px 0;
    }

    .feature-card {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        padding: 12px;
    }

    .feature-card h4 {
        font-size: 9.5pt;
        font-weight: 700;
        color: #0f172a;
        margin-bottom: 5px;
        display: flex;
        align-items: center;
        gap: 6px;
    }

    .feature-card p {
        font-size: 8.5pt;
        color: #475569;
        margin-bottom: 0;
        line-height: 1.4;
    }

    /* SVG Diagrams styling */
    .diagram-container {
        background: #0b1120;
        border: 1px solid #1e293b;
        border-radius: 8px;
        padding: 16px;
        margin: 14px 0;
        text-align: center;
    }

    .diagram-title {
        color: #94a3b8;
        font-size: 8.5pt;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 10px;
        display: block;
    }

    /* Badges */
    .badge {
        display: inline-block;
        font-size: 7.5pt;
        font-weight: 700;
        padding: 2px 6px;
        border-radius: 4px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .badge-blue { background: #e0f2fe; color: #0284c7; border: 1px solid #bae6fd; }
    .badge-green { background: #dcfce7; color: #16a34a; border: 1px solid #bbf7d0; }
    .badge-amber { background: #fef3c7; color: #d97706; border: 1px solid #fde68a; }
    .badge-red { background: #fee2e2; color: #dc2626; border: 1px solid #fecaca; }
    .badge-purple { background: #f3e8ff; color: #9333ea; border: 1px solid #e9d5ff; }

    .highlight {
        background-color: #fef08a;
        padding: 1px 4px;
        border-radius: 2px;
    }
</style>
</head>
<body>

<!-- ═══════════════════════════════════════════════════════════════════════════ -->
<!-- COVER PAGE                                                                -->
<!-- ═══════════════════════════════════════════════════════════════════════════ -->
<div class="cover-page">
    <div>
        <div class="cover-badge">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline></svg>
            System Architecture & Technical Manual
        </div>
        <h1 class="cover-title">A.U.R.I.X</h1>
        <div class="cover-subtitle">
            Autonomous Universal Reasoning & Interaction Executive
            <br>
            <span style="font-size: 11pt; color: #cbd5e1;">A Fully Autonomous, Edge-Governed, Privacy-First Desktop AI Agent</span>
        </div>

        <div class="cover-invariants">
            <span class="inv-tag">Zero Network Sockets</span>
            <span class="inv-tag">100% On-Device Execution</span>
            <span class="inv-tag">Bare-Metal Hardware Governor</span>
            <span class="inv-tag">Continuous QLoRA Learning</span>
            <span class="inv-tag">Autonomous Self-Healing</span>
        </div>
    </div>

    <div>
        <div class="cover-meta-grid">
            <div class="cover-meta-item">
                <h4>System Version</h4>
                <p>v0.1.0 (Production Core)</p>
            </div>
            <div class="cover-meta-item">
                <h4>Primary Core Stack</h4>
                <p>Rust 2021 + PyO3 FFI</p>
            </div>
            <div class="cover-meta-item">
                <h4>AI Inference & LoRA</h4>
                <p>Qwen 3:4B (4-Bit NF4) + Unsloth</p>
            </div>
            <div class="cover-meta-item">
                <h4>Desktop Interface</h4>
                <p>Slint 1.8 Native GUI</p>
            </div>
            <div class="cover-meta-item">
                <h4>Audio Engine</h4>
                <p>Whisper.cpp (STT) + Piper (TTS)</p>
            </div>
            <div class="cover-meta-item">
                <h4>Persistence & Analytics</h4>
                <p>SQLite + DuckDB + ChromaDB</p>
            </div>
        </div>
    </div>

    <div class="cover-footer">
        <div class="cover-footer-text">
            <strong>AURIX Engineering Team</strong> &bull; Comprehensive System Documentation<br>
            Target Hardware Profile: 16 GB Host RAM (12 GB Ceiling) &bull; NVIDIA RTX 4060 8 GB VRAM (6 GB Ceiling)
        </div>
        <div style="font-family: 'Space Grotesk', sans-serif; font-size: 12pt; font-weight: 700; color: #38bdf8;">
            CONFIDENTIAL &bull; INTERNAL
        </div>
    </div>
</div>

<div class="page-break"></div>

<!-- ═══════════════════════════════════════════════════════════════════════════ -->
<!-- EXECUTIVE SUMMARY & TABLE OF CONTENTS                                     -->
<!-- ═══════════════════════════════════════════════════════════════════════════ -->

<h1><span class="section-num">1</span> Executive Summary & Architectural Invariants</h1>

<p>
    <strong>A.U.R.I.X (Autonomous Universal Reasoning & Interaction Executive)</strong> is a state-of-the-art, 
    locally executing autonomous desktop AI agent. Engineered to operate completely on-device without cloud telemetry, 
    remote APIs, or external server dependencies, AURIX combines <strong>bare-metal systems programming (Rust)</strong> 
    with <strong>modern deep learning (PyTorch, Unsloth, Qwen 3:4B)</strong> and a <strong>reactive GUI (Slint)</strong>.
</p>

<div class="card-grid-3">
    <div class="feature-card">
        <h4><span class="badge badge-blue">Zero-Socket</span> Air-Gapped Privacy</h4>
        <p>No outbound HTTP sockets, WebSockets, or cloud endpoints for core reasoning. Zero data leakage of terminal commands or UI states.</p>
    </div>
    <div class="feature-card">
        <h4><span class="badge badge-green">Governor</span> Hard Resource Bounds</h4>
        <p>Real-time OS monitoring suspends model operations if RAM exceeds 12.0 GB or VRAM exceeds 6.0 GB, preventing desktop freezes.</p>
    </div>
    <div class="feature-card">
        <h4><span class="badge badge-purple">Self-Healing</span> Autonomous Recovery</h4>
        <p>Automatic regex traceback extraction, QLoRA error diagnosis, candidate patch generation, and strict N=3 retry mitigation ceiling.</p>
    </div>
</div>

<div class="toc-container">
    <div class="toc-title">Table of Contents & Blueprint Navigation</div>
    <div class="toc-grid">
        <div class="toc-item"><span class="title">1. Executive Summary & Invariants</span><span class="desc">Design Pillars & Principles</span></div>
        <div class="toc-item"><span class="title">2. Master System Architecture</span><span class="desc">Multi-Tier Runtime Topology</span></div>
        <div class="toc-item"><span class="title">3. Subsystem 1: Rust Core Engine</span><span class="desc">Governor, Sandbox & Observers</span></div>
        <div class="toc-item"><span class="title">4. Subsystem 2: AI Engine & Inference</span><span class="desc">Qwen 3:4B & Unsloth QLoRA Loop</span></div>
        <div class="toc-item"><span class="title">5. Subsystem 3: Data Pipeline & Memory</span><span class="desc">SQLite, DuckDB, Vector Store</span></div>
        <div class="toc-item"><span class="title">6. Subsystem 4: Command Center & Audio</span><span class="desc">Slint GUI, Whisper & Piper</span></div>
        <div class="toc-item"><span class="title">7. End-to-End Operational Workflows</span><span class="desc">Action, Self-Healing & Eviction</span></div>
        <div class="toc-item"><span class="title">8. Configuration & Deployment Guide</span><span class="desc">config.toml & Build Steps</span></div>
    </div>
</div>

<h2>Core System Invariants</h2>
<table class="avoid-break">
    <thead>
        <tr>
            <th style="width: 25%;">Invariant</th>
            <th style="width: 35%;">Implementation Mechanism</th>
            <th style="width: 40%;">Architectural Purpose</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td><strong>In-Process FFI Execution</strong></td>
            <td>PyO3 C-ABI native extension module (<code>aurix_core.pyd</code>)</td>
            <td>Zero IPC overhead, zero localhost TCP ports, atomic memory sharing across Rust and Python runtimes.</td>
        </tr>
        <tr>
            <td><strong>Hard Resource Ceilings</strong></td>
            <td>Rust <code>sysinfo</code> + <code>nvml-wrapper</code> background thread (1000ms poll)</td>
            <td>Strictly prevents system out-of-memory (OOM) crashes by enforcing 12.0 GB RAM and 6.0 GB VRAM limits.</td>
        </tr>
        <tr>
            <td><strong>Path Canonicalization Jail</strong></td>
            <td>Rust <code>fs::canonicalize</code> & boundary prefix verification</td>
            <td>Mitigates path traversal attacks (<code>../</code>), symlink escapes, UNC paths, and unauthorized disk writes.</td>
        </tr>
        <tr>
            <td><strong>Continuous QLoRA Learning</strong></td>
            <td>Unsloth 4-bit NF4 fine-tuning on live telemetry streams</td>
            <td>Student model continuously adapts to user workflows locally without full parameter recomputation.</td>
        </tr>
        <tr>
            <td><strong>Autonomous Self-Healing Loop</strong></td>
            <td>Regex traceback parser + LLM patch generation (Max N=3)</td>
            <td>Automatically repairs failed terminal commands with a 5-second UI countdown override for user intervention.</td>
        </tr>
    </tbody>
</table>

<div class="page-break"></div>

<!-- ═══════════════════════════════════════════════════════════════════════════ -->
<!-- MASTER SYSTEM ARCHITECTURE & TOPOLOGY                                     -->
<!-- ═══════════════════════════════════════════════════════════════════════════ -->

<h1><span class="section-num">2</span> Master System Architecture</h1>

<p>
    AURIX employs a <strong>tri-tier modular architecture</strong> where each tier maintains strict separation of concerns, 
    communicating via zero-overhead native bindings, shared atomic memory, and embedded database layers.
</p>

<!-- SVG Architecture Diagram -->
<div class="diagram-container avoid-break">
    <span class="diagram-title">AURIX Unified System Topology & Component Interactions</span>
    <svg width="100%" height="320" viewBox="0 0 780 320" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="gradRust" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#ea580c"/><stop offset="100%" stop-color="#9a3412"/></linearGradient>
            <linearGradient id="gradPy" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#0284c7"/><stop offset="100%" stop-color="#0369a1"/></linearGradient>
            <linearGradient id="gradUI" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#7c3aed"/><stop offset="100%" stop-color="#5b21b6"/></linearGradient>
            <linearGradient id="gradData" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#059669"/><stop offset="100%" stop-color="#047857"/></linearGradient>
        </defs>

        <!-- Tier 1: Slint UI & Audio -->
        <rect x="20" y="20" width="220" height="280" rx="8" fill="#1e1b4b" stroke="#6366f1" stroke-width="1.5"/>
        <text x="130" y="45" fill="#c7d2fe" font-family="'Space Grotesk', sans-serif" font-weight="700" font-size="12" text-anchor="middle">NATIVE UI & AUDIO</text>
        <rect x="35" y="60" width="190" height="40" rx="4" fill="#312e81" stroke="#4338ca"/>
        <text x="130" y="85" fill="#ffffff" font-family="sans-serif" font-size="10" font-weight="600" text-anchor="middle">Slint Command Center</text>
        <rect x="35" y="110" width="190" height="40" rx="4" fill="#312e81" stroke="#4338ca"/>
        <text x="130" y="135" fill="#ffffff" font-family="sans-serif" font-size="10" font-weight="600" text-anchor="middle">Whisper.cpp STT (16kHz)</text>
        <rect x="35" y="160" width="190" height="40" rx="4" fill="#312e81" stroke="#4338ca"/>
        <text x="130" y="185" fill="#ffffff" font-family="sans-serif" font-size="10" font-weight="600" text-anchor="middle">Piper Neural TTS (ONNX)</text>
        <rect x="35" y="210" width="190" height="75" rx="4" fill="#312e81" stroke="#4338ca"/>
        <text x="130" y="235" fill="#a5b4fc" font-family="sans-serif" font-size="9.5" font-weight="700" text-anchor="middle">Interactive Modals</text>
        <text x="130" y="255" fill="#cbd5e1" font-family="sans-serif" font-size="8.5" text-anchor="middle">&bull; 5s Self-Healing Countdown</text>
        <text x="130" y="272" fill="#cbd5e1" font-family="sans-serif" font-size="8.5" text-anchor="middle">&bull; Trust Token Review Card</text>

        <!-- Tier 2: Core Engine (Rust) -->
        <rect x="280" y="20" width="220" height="280" rx="8" fill="#431407" stroke="#f97316" stroke-width="1.5"/>
        <text x="390" y="45" fill="#ffedd5" font-family="'Space Grotesk', sans-serif" font-weight="700" font-size="12" text-anchor="middle">CORE ENGINE (RUST)</text>
        <rect x="295" y="60" width="190" height="50" rx="4" fill="#7c2d12" stroke="#ea580c"/>
        <text x="390" y="82" fill="#ffffff" font-family="sans-serif" font-size="10" font-weight="600" text-anchor="middle">Hardware Governor</text>
        <text x="390" y="98" fill="#fdba74" font-family="sans-serif" font-size="8" text-anchor="middle">RAM ≤ 12GB | VRAM ≤ 6GB (1000ms)</text>
        <rect x="295" y="120" width="190" height="45" rx="4" fill="#7c2d12" stroke="#ea580c"/>
        <text x="390" y="142" fill="#ffffff" font-family="sans-serif" font-size="10" font-weight="600" text-anchor="middle">File Jail Sandbox</text>
        <text x="390" y="156" fill="#fdba74" font-family="sans-serif" font-size="8" text-anchor="middle">secure_path_resolve()</text>
        <rect x="295" y="175" width="190" height="45" rx="4" fill="#7c2d12" stroke="#ea580c"/>
        <text x="390" y="196" fill="#ffffff" font-family="sans-serif" font-size="10" font-weight="600" text-anchor="middle">OS Observers & Interceptors</text>
        <text x="390" y="210" fill="#fdba74" font-family="sans-serif" font-size="8" text-anchor="middle">UIA Tree COM + PTY Interceptor</text>
        <rect x="295" y="230" width="190" height="55" rx="4" fill="#7c2d12" stroke="#ea580c"/>
        <text x="390" y="252" fill="#ffffff" font-family="sans-serif" font-size="10" font-weight="600" text-anchor="middle">PyO3 FFI C-ABI Bridge</text>
        <text x="390" y="270" fill="#fed7aa" font-family="sans-serif" font-size="8" text-anchor="middle">AtomicBool / SystemState</text>

        <!-- Tier 3: AI Engine & Data Pipeline -->
        <rect x="540" y="20" width="220" height="280" rx="8" fill="#082f49" stroke="#0ea5e9" stroke-width="1.5"/>
        <text x="650" y="45" fill="#e0f2fe" font-family="'Space Grotesk', sans-serif" font-weight="700" font-size="12" text-anchor="middle">AI ENGINE & DATA PIPELINE</text>
        <rect x="555" y="60" width="190" height="45" rx="4" fill="#0369a1" stroke="#0284c7"/>
        <text x="650" y="82" fill="#ffffff" font-family="sans-serif" font-size="10" font-weight="600" text-anchor="middle">Qwen 3:4B Local Inference</text>
        <text x="650" y="96" fill="#bae6fd" font-family="sans-serif" font-size="8" text-anchor="middle">4-bit NF4 via Unsloth</text>
        <rect x="555" y="115" width="190" height="50" rx="4" fill="#0369a1" stroke="#0284c7"/>
        <text x="650" y="136" fill="#ffffff" font-family="sans-serif" font-size="10" font-weight="600" text-anchor="middle">Continuous QLoRA Loop</text>
        <text x="650" y="152" fill="#bae6fd" font-family="sans-serif" font-size="8" text-anchor="middle">Graceful VRAM Eviction Manager</text>
        <rect x="555" y="175" width="190" height="45" rx="4" fill="#0369a1" stroke="#0284c7"/>
        <text x="650" y="196" fill="#ffffff" font-family="sans-serif" font-size="10" font-weight="600" text-anchor="middle">Self-Healing Diagnostics</text>
        <text x="650" y="210" fill="#bae6fd" font-family="sans-serif" font-size="8" text-anchor="middle">TracebackAnalyzer (Max N=3)</text>
        <rect x="555" y="230" width="190" height="55" rx="4" fill="#0369a1" stroke="#0284c7"/>
        <text x="650" y="250" fill="#ffffff" font-family="sans-serif" font-size="10" font-weight="600" text-anchor="middle">Dual Storage & Vector Store</text>
        <text x="650" y="266" fill="#bae6fd" font-family="sans-serif" font-size="8" text-anchor="middle">SQLite + DuckDB + Chroma/FAISS</text>

        <!-- Connecting Lines -->
        <line x1="240" y1="100" x2="280" y2="100" stroke="#818cf8" stroke-width="2" stroke-dasharray="4"/>
        <line x1="240" y1="255" x2="280" y2="255" stroke="#f472b6" stroke-width="2"/>
        <line x1="500" y1="85" x2="540" y2="85" stroke="#38bdf8" stroke-width="2"/>
        <line x1="500" y1="255" x2="540" y2="255" stroke="#34d399" stroke-width="2"/>
    </svg>
</div>

<h2>Runtime Subsystem Matrix</h2>
<table>
    <thead>
        <tr>
            <th>Module Name</th>
            <th>Primary Language</th>
            <th>Key Crates / Libraries</th>
            <th>Core Responsibility</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td><code>core_engine</code></td>
            <td><span class="badge badge-amber">Rust 2021</span></td>
            <td><code>pyo3</code>, <code>sysinfo</code>, <code>nvml-wrapper</code>, <code>uiautomation</code></td>
            <td>Hardware governor, security sandbox, Windows UI Automation tree, headless PTY execution.</td>
        </tr>
        <tr>
            <td><code>ai_engine</code></td>
            <td><span class="badge badge-blue">Python 3.10+</span></td>
            <td><code>torch</code>, <code>unsloth</code>, <code>transformers</code>, <code>trl</code></td>
            <td>Local 4-bit LLM generation, QLoRA continuous training loop, graceful VRAM memory manager.</td>
        </tr>
        <tr>
            <td><code>data_pipeline</code></td>
            <td><span class="badge badge-green">Python / SQL</span></td>
            <td><code>sqlite3</code>, <code>duckdb</code>, <code>chromadb</code>, <code>faiss</code></td>
            <td>Telemetry ingestion daemon, OLAP analytics, self-healing traceback parser, semantic vector store.</td>
        </tr>
        <tr>
            <td><code>native_ui</code></td>
            <td><span class="badge badge-purple">Rust / Slint</span></td>
            <td><code>slint 1.8</code>, <code>windows-sys</code>, <code>piper</code>, <code>whisper</code></td>
            <td>GPU-accelerated desktop dashboard, speech-to-text, text-to-speech, security review cards.</td>
        </tr>
    </tbody>
</table>

<div class="page-break"></div>

<!-- ═══════════════════════════════════════════════════════════════════════════ -->
<!-- SUBSYSTEM 1: RUST CORE ENGINE                                             -->
<!-- ═══════════════════════════════════════════════════════════════════════════ -->

<h1><span class="section-num">3</span> Subsystem 1: Rust Core Engine (`core_engine`)</h1>

<p>
    The <code>core_engine</code> is the foundation of AURIX, compiled as a native shared library (<code>cdylib</code>) 
    and imported directly by Python via <strong>PyO3</strong>. It executes bare-metal system tasks where memory safety, 
    low latency, and direct OS APIs are essential.
</p>

<h2>1. Hardware Resource Governor (`governor/`)</h2>
<p>
    The Hardware Resource Governor is a dedicated watchdog thread designed to operate reliably on resource-constrained 
    machines (e.g., 16 GB RAM / 8 GB VRAM). It continuously queries system metrics to protect the desktop environment 
    from being starved by heavy machine learning operations.
</p>

<div class="card-grid-2 avoid-break">
    <div class="feature-card">
        <h4><span class="badge badge-amber">RAM Ceiling</span> 12.0 GiB (75% Utilization)</h4>
        <p>Monitored via <code>sysinfo::System</code>. If active system RAM crosses 12.0 GB, the governor instantly signals the Python QLoRA loop to halt.</p>
    </div>
    <div class="feature-card">
        <h4><span class="badge badge-red">VRAM Ceiling</span> 6.0 GiB (75% Utilization)</h4>
        <p>Monitored via <code>nvml-wrapper</code> (NVIDIA Management Library). Protects device 0 VRAM from out-of-memory kernel panics.</p>
    </div>
</div>

<h3>Lock-Free Atomic Signaling (`governor/atomic_state.rs`)</h3>
<p>
    To eliminate GIL (Global Interpreter Lock) contention and avoid network sockets, the governor writes to an 
    <code>Arc&lt;AtomicBool&gt;</code> using sequentially consistent memory ordering (<code>Ordering::SeqCst</code>). 
    This provides instantaneous cross-thread signaling with zero allocation overhead.
</p>

<pre class="code-rust"><code>// core_engine/src/governor/atomic_state.rs
static GLOBAL_SUSPEND_FLAG: AtomicBool = AtomicBool::new(false);

pub fn set_suspend_flag(suspend: bool) {
    GLOBAL_SUSPEND_FLAG.store(suspend, Ordering::SeqCst);
}

#[pyclass]
#[derive(Clone)]
pub struct SystemState {
    is_suspended: Arc&lt;AtomicBool&gt;,
}

#[pymethods]
impl SystemState {
    pub fn check_suspended(&self) -> bool {
        self.is_suspended.load(Ordering::SeqCst)
    }
}</code></pre>

<h2>2. Security Sandbox & File Jail (`sandbox/file_jail.rs`)</h2>
<p>
    Autonomous agents must never execute uncontrolled file writes or deletions. The <strong>File Jail</strong> enforces 
    path canonicalization on every path requested by the LLM or user before any file descriptor is opened.
</p>

<div class="callout callout-warning avoid-break">
    <div class="callout-title">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>
        Canonicalization Security Protocol
    </div>
    If a requested file path resolves outside the designated <code>ALLOWED_ROOT</code> (e.g. <code>C:\Windows\System32</code> or via <code>..\..\</code> traversal), <code>secure_path_resolve()</code> triggers an immediate safety panic, which PyO3 catches and translates into a Python <code>RuntimeError("Access Denied")</code>.
</div>

<pre class="code-rust"><code>// Canonicalization containment check algorithm
pub fn secure_path_resolve(base_dir: &Path, target: &str) -> Result&lt;PathBuf, io::Error&gt; {
    let canon_base = fs::canonicalize(base_dir)?;
    let candidate = if Path::new(target).is_absolute() {
        PathBuf::from(target)
    } else {
        base_dir.join(target)
    };
    let canon_candidate = fs::canonicalize(&candidate)
        .or_else(|_| candidate.parent().unwrap().canonicalize().map(|p| p.join(candidate.file_name().unwrap())))?;

    if !canon_candidate.starts_with(&canon_base) {
        panic!("Access Denied: path {:?} escapes jail boundary {:?}", canon_candidate, canon_base);
    }
    Ok(canon_candidate)
}</code></pre>

<h2>3. Operating System Observers (`observers/`)</h2>
<p>
    AURIX grounds its reasoning in real-time desktop context through two native observer pipelines:
</p>
<ul style="margin-left: 20px; margin-bottom: 12px; font-size: 9pt;">
    <li><strong>Windows UI Automation COM Observer (`uia_tree.rs`):</strong> Leverages the Windows UI Automation COM interface to capture the focused control, window class name, automation ID, and screen-space pixel coordinates without taking invasive screen captures.</li>
    <li><strong>PTY Child Process Interceptor (`terminal_hook.rs`):</strong> Spawns sandboxed shell commands using <code>cmd.exe /C</code> with <code>CREATE_NO_WINDOW (0x08000000)</code> flags to suppress console flashes, capturing stdout, stderr, and exit codes into a structured data transfer object.</li>
</ul>

<div class="page-break"></div>

<!-- ═══════════════════════════════════════════════════════════════════════════ -->
<!-- SUBSYSTEM 2: AI ENGINE & CONTINUOUS LEARNING                              -->
<!-- ═══════════════════════════════════════════════════════════════════════════ -->

<h1><span class="section-num">4</span> Subsystem 2: AI Engine & Continuous Learning (`ai_engine`)</h1>

<p>
    The <code>ai_engine</code> executes local language model inference and continuous background fine-tuning. 
    It is specifically architected to run alongside the Rust governor with <strong>deterministic VRAM governance</strong>.
</p>

<h2>1. Qwen 3:4B Local Inference Engine (`llm_inference.py`)</h2>
<p>
    AURIX utilizes the <strong>Qwen 3:4B / Qwen 2.5 3B</strong> model family, loaded in <strong>4-bit NormalFloat (NF4)</strong> 
    quantization via <code>bitsandbytes</code> and <code>Unsloth</code>. This reduces the base model memory footprint from ~10 GB in FP16 to ~2.5 GB in VRAM, leaving ample room for context caches.
</p>

<pre class="code-py"><code># Prompt Template Structure with Multi-Modal Context Grounding
PROMPT_TEMPLATE = """### Instruction:
{instruction}

### Input:
{input}

### Response:
{output}"""</code></pre>

<h2>2. Unsloth QLoRA Continuous Training Loop (`training/qlora_loop.py`)</h2>
<p>
    AURIX continuously fine-tunes a student adapter on user execution traces. To prevent GPU out-of-memory errors on an 8 GB RTX 4060, the training loop uses a tightly constrained hyperparameter profile:
</p>

<table class="avoid-break">
    <thead>
        <tr>
            <th>Parameter</th>
            <th>Value</th>
            <th>Rationale & VRAM Impact</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td><strong>Micro-Batch Size</strong></td>
            <td><code>1</code></td>
            <td>Minimizes peak VRAM consumption per forward/backward pass.</td>
        </tr>
        <tr>
            <td><strong>Gradient Accumulation</strong></td>
            <td><code>8</code></td>
            <td>Yields an effective batch size of 8 without increasing active VRAM.</td>
        </tr>
        <tr>
            <td><strong>LoRA Rank (r) / Alpha</strong></td>
            <td><code>r=16, alpha=32</code></td>
            <td>Targets all attention + MLP linear layers (<code>q, k, v, o, gate, up, down</code>).</td>
        </tr>
        <tr>
            <td><strong>Gradient Checkpointing</strong></td>
            <td><code>"unsloth"</code></td>
            <td>Recomputes activations during backward pass, saving ~40% VRAM.</td>
        </tr>
        <tr>
            <td><strong>Optimiser</strong></td>
            <td><code>"adamw_8bit"</code></td>
            <td>Halves optimizer state memory from 8 bytes/param to 4 bytes/param.</td>
        </tr>
    </tbody>
</table>

<h2>3. Graceful VRAM Eviction Manager (`training/memory_manager.py`)</h2>
<p>
    The <code>GracefulMemoryManager</code> bridges the PyTorch training loop with the Rust hardware governor. 
    At every training step, the <code>GovernorCallback</code> queries <code>aurix_core.SystemState.check_suspended()</code>.
</p>

<!-- SVG Eviction Diagram -->
<div class="diagram-container avoid-break">
    <span class="diagram-title">Graceful VRAM Eviction & Hardware Recovery State Machine</span>
    <svg width="100%" height="180" viewBox="0 0 720 180" xmlns="http://www.w3.org/2000/svg">
        <rect x="20" y="55" width="130" height="70" rx="6" fill="#1e293b" stroke="#0284c7" stroke-width="1.5"/>
        <text x="85" y="85" fill="#ffffff" font-family="sans-serif" font-size="10" font-weight="700" text-anchor="middle">1. SFT Step End</text>
        <text x="85" y="105" fill="#94a3b8" font-family="sans-serif" font-size="8" text-anchor="middle">Poll Rust Atomic Flag</text>

        <path d="M 150 90 L 190 90" stroke="#38bdf8" stroke-width="2" marker-end="url(#arrow)"/>

        <rect x="190" y="55" width="140" height="70" rx="6" fill="#78350f" stroke="#f59e0b" stroke-width="1.5"/>
        <text x="260" y="85" fill="#ffffff" font-family="sans-serif" font-size="10" font-weight="700" text-anchor="middle">2. Spike Detected</text>
        <text x="260" y="105" fill="#fde68a" font-family="sans-serif" font-size="8" text-anchor="middle">RAM > 12GB | VRAM > 6GB</text>

        <path d="M 330 90 L 370 90" stroke="#f59e0b" stroke-width="2"/>

        <rect x="370" y="55" width="160" height="70" rx="6" fill="#831843" stroke="#f43f5e" stroke-width="1.5"/>
        <text x="450" y="80" fill="#ffffff" font-family="sans-serif" font-size="10" font-weight="700" text-anchor="middle">3. Emergency Checkpoint</text>
        <text x="450" y="98" fill="#fbcfe8" font-family="sans-serif" font-size="8" text-anchor="middle">Save LoRA weights (3-8s)</text>
        <text x="450" y="112" fill="#fbcfe8" font-family="sans-serif" font-size="8" text-anchor="middle">torch.cuda.empty_cache()</text>

        <path d="M 530 90 L 570 90" stroke="#10b981" stroke-width="2"/>

        <rect x="570" y="55" width="130" height="70" rx="6" fill="#064e3b" stroke="#10b981" stroke-width="1.5"/>
        <text x="635" y="85" fill="#ffffff" font-family="sans-serif" font-size="10" font-weight="700" text-anchor="middle">4. Sleep & Resume</text>
        <text x="635" y="105" fill="#a7f3d0" font-family="sans-serif" font-size="8" text-anchor="middle">Resume on Normalcy</text>
    </svg>
</div>

<div class="callout callout-danger avoid-break">
    <div class="callout-title">Mechanical HDD Checkpoint Latency Mitigation</div>
    On mechanical spinning hard drives, flushing LoRA weights and optimizer states blocks I/O for 3 to 8 seconds. <code>GracefulMemoryManager</code> decouples checkpoint writes from the active GUI thread to keep the user interface responsive during emergency evictions.
</div>

<div class="page-break"></div>

<!-- ═══════════════════════════════════════════════════════════════════════════ -->
<!-- SUBSYSTEM 3: DATA PIPELINE & SELF-HEALING                                 -->
<!-- ═══════════════════════════════════════════════════════════════════════════ -->

<h1><span class="section-num">5</span> Subsystem 3: Data Pipeline & Self-Healing (`data_pipeline`)</h1>

<p>
    The <code>data_pipeline</code> provides structured telemetry logging, analytical query processing, 
    experience replay buffering, and autonomous error recovery.
</p>

<h2>1. Dual Storage Engine: SQLite + DuckDB (`storage/`)</h2>
<p>
    AURIX pairs <strong>SQLite</strong> for concurrent transaction logging with <strong>DuckDB</strong> for high-speed in-memory OLAP analytics.
</p>

<table class="avoid-break">
    <thead>
        <tr>
            <th>Table Name</th>
            <th>Primary Columns</th>
            <th>Operational Purpose</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td><code>execution_logs</code></td>
            <td><code>log_id, session_id, timestamp, action_type, target_command, status, return_code, error_traceback</code></td>
            <td>Tracks every terminal command and UI action. Fed into the self-healing engine upon failure.</td>
        </tr>
        <tr>
            <td><code>performance_telemetry</code></td>
            <td><code>log_id, timestamp, ram_allocated_gb, vram_peak_gb, training_state</code></td>
            <td>Time-series metrics recorded at 1-second intervals from the Rust governor.</td>
        </tr>
        <tr>
            <td><code>security_audit_trails</code></td>
            <td><code>audit_id, timestamp, requested_path, operation_type, trust_token_id, approval_status, sandbox_enforced</code></td>
            <td>Immutable audit log of all sandbox interactions and Trust Token approvals.</td>
        </tr>
    </tbody>
</table>

<h2>2. Autonomous Self-Healing Diagnostic Engine (`self_healing/`)</h2>
<p>
    When a terminal command returns a non-zero exit code, the <strong>Self-Healing Engine</strong> triggers an automated recovery workflow:
</p>

<div class="avoid-break">
    <ol style="margin-left: 20px; font-size: 9pt; line-height: 1.5;">
        <li><strong>Traceback Parsing:</strong> <code>TracebackAnalyzer.parse_stderr()</code> scans backward through the stderr stream using regex to locate the core exception type, message, and offending source line.</li>
        <li><strong>Diagnostic Context Generation:</strong> A specialized diagnostic prompt is synthesized containing the original command, error diagnosis, and traceback.</li>
        <li><strong>Candidate Patch Synthesis:</strong> The local Qwen 3:4B model generates a corrected script.</li>
        <li><strong>Strict N=3 Retry Ceiling:</strong> To prevent infinite self-healing loops, the engine caps automated retry attempts at 3. Once exceeded, control yields to the user.</li>
        <li><strong>5-Second Override Modal:</strong> The proposed patch and countdown are sent to the Slint GUI, allowing the user to cancel or modify the fix before execution.</li>
    </ol>
</div>

<pre class="code-py"><code># Self-Healing Execution Failure Handler
def handle_execution_failure(self, task_id: str, failed_script: str, stderr_stream: str) -> Dict[str, Any]:
    current_attempts = self.retry_tracker.get(task_id, 0)
    if current_attempts >= self.MAX_RETRIES:
        return {"status": "HALTED_MAX_RETRIES_EXCEEDED", "show_alert_modal": True}
        
    diagnostic = TracebackAnalyzer.parse_stderr(stderr_stream)
    prompt = self._construct_diagnostic_prompt(failed_script, diagnostic)
    proposed_patch = self._query_model_for_patch(prompt)
    
    self.retry_tracker[task_id] = current_attempts + 1
    return {
        "status": "PROPOSED_PATCH_READY",
        "attempt": self.retry_tracker[task_id],
        "proposed_patch": proposed_patch,
        "countdown_seconds": 5
    }</code></pre>

<h2>3. Semantic Compiler & Skill Vector Store (`vector_store/` & `compiler/`)</h2>
<ul style="margin-left: 20px; margin-bottom: 12px; font-size: 9pt;">
    <li><strong>Semantic Compiler:</strong> Automatically detects and parameterizes hardcoded ports (e.g. <code>--port=3000</code> -> <code>${PORT_NUMBER_1}</code>) and directory paths into generalized automation scripts.</li>
    <li><strong>Experience Replay Buffer:</strong> Samples training batches with an <strong>80/20 ratio</strong> (80% foundational coding knowledge, 20% live user experience) to prevent catastrophic forgetting.</li>
    <li><strong>Skill Vector Store:</strong> Uses <strong>ChromaDB</strong> for persistent cosine semantic retrieval and <strong>FAISS <code>IndexFlatL2</code></strong> for microsecond bare-metal L2 vector search over 384-dimensional embeddings.</li>
</ul>

<div class="page-break"></div>

<!-- ═══════════════════════════════════════════════════════════════════════════ -->
<!-- SUBSYSTEM 4: NATIVE COMMAND CENTER & AUDIO                                -->
<!-- ═══════════════════════════════════════════════════════════════════════════ -->

<h1><span class="section-num">6</span> Subsystem 4: Native Command Center & Audio (`native_ui`)</h1>

<p>
    The <code>native_ui</code> subsystem provides a responsive desktop user interface and zero-cloud voice interaction. 
    Built with <strong>Slint 1.8</strong>, it renders natively on the GPU with minimal memory overhead.
</p>

<h2>1. Slint Declarative Command Center (`ui/`)</h2>
<p>
    The interface features a cyber-industrial dark theme with real-time gauges and security controls:
</p>

<div class="card-grid-3 avoid-break">
    <div class="feature-card">
        <h4><span class="badge badge-blue">Telemetry Dials</span> Live Hardware Gauges</h4>
        <p>Real-time SVG arc meters displaying CPU load, RAM allocation, GPU VRAM peak, and active process state.</p>
    </div>
    <div class="feature-card">
        <h4><span class="badge badge-amber">Review Cards</span> Trust Token Validation</h4>
        <p>Interactive cards requiring user approval before executing high-risk file modifications or system commands.</p>
    </div>
    <div class="feature-card">
        <h4><span class="badge badge-purple">Alert Modals</span> 5s Self-Healing Timer</h4>
        <p>Floating alert modal displaying failed command diffs, error tracebacks, and an animated 5-second countdown timer.</p>
    </div>
</div>

<h2>2. Offline Audio Subsystem: Whisper STT & Piper TTS (`audio/`)</h2>

<div class="card-grid-2 avoid-break">
    <div class="feature-card">
        <h4><span class="badge badge-green">Speech-to-Text</span> Whisper.cpp (<code>whisper_stt.rs</code>)</h4>
        <p>
            Captures 16 kHz 16-bit mono PCM microphone streams and performs offline GGML transcription. 
            Dispatches recognized voice commands directly into the AURIX event bus without cloud latency.
        </p>
    </div>
    <div class="feature-card">
        <h4><span class="badge badge-blue">Text-to-Speech</span> Piper Neural TTS (<code>piper_tts.rs</code>)</h4>
        <p>
            Synthesizes responses using local ONNX voice models (e.g. <code>en_US-lessac-medium.onnx</code>). 
            Streams audio directly to the default audio output with sub-50ms synthesis latency.
        </p>
    </div>
</div>

<pre class="code-slint"><code>// Slint UI Architecture — Telemetry & Review Card Binding
export component AurixCommandCenter inherits Window {
    in-out property &lt;float&gt; cpu_usage: 0.15;
    in-out property &lt;string&gt; ram_display: "8.2 / 16.0 GB";
    in-out property &lt;string&gt; toast_message: "";
    callback send_message(string);
    callback review_approve();
    callback alert_retry();
    
    // Declarative reactive layout components...
}</code></pre>

<div class="page-break"></div>

<!-- ═══════════════════════════════════════════════════════════════════════════ -->
<!-- END-TO-END OPERATIONAL WORKFLOWS                                          -->
<!-- ═══════════════════════════════════════════════════════════════════════════ -->

<h1><span class="section-num">7</span> End-to-End Operational Workflows</h1>

<p>
    The following workflows illustrate how AURIX's subsystems coordinate across real-world operational scenarios.
</p>

<h2>Workflow A: Voice / Text Command to Sandboxed Execution</h2>
<!-- SVG Flowchart A -->
<div class="diagram-container avoid-break">
    <span class="diagram-title">Standard Execution Flow with Security Sandbox & Audio Loop</span>
    <svg width="100%" height="100" viewBox="0 0 740 100" xmlns="http://www.w3.org/2000/svg">
        <rect x="10" y="25" width="100" height="50" rx="4" fill="#1e293b" stroke="#38bdf8"/>
        <text x="60" y="48" fill="#ffffff" font-size="8.5" font-weight="700" text-anchor="middle">1. User Input</text>
        <text x="60" y="62" fill="#94a3b8" font-size="7.5" text-anchor="middle">Voice or GUI</text>

        <path d="M 110 50 L 140 50" stroke="#38bdf8" stroke-width="1.5"/>

        <rect x="140" y="25" width="110" height="50" rx="4" fill="#1e293b" stroke="#818cf8"/>
        <text x="195" y="48" fill="#ffffff" font-size="8.5" font-weight="700" text-anchor="middle">2. Qwen Inference</text>
        <text x="195" y="62" fill="#c7d2fe" font-size="7.5" text-anchor="middle">Vector Context</text>

        <path d="M 250 50 L 280 50" stroke="#818cf8" stroke-width="1.5"/>

        <rect x="280" y="25" width="120" height="50" rx="4" fill="#78350f" stroke="#f59e0b"/>
        <text x="340" y="48" fill="#ffffff" font-size="8.5" font-weight="700" text-anchor="middle">3. File Jail Check</text>
        <text x="340" y="62" fill="#fde68a" font-size="7.5" text-anchor="middle">Canonicalize Path</text>

        <path d="M 400 50 L 430 50" stroke="#f59e0b" stroke-width="1.5"/>

        <rect x="430" y="25" width="130" height="50" rx="4" fill="#1e293b" stroke="#34d399"/>
        <text x="495" y="48" fill="#ffffff" font-size="8.5" font-weight="700" text-anchor="middle">4. Headless PTY</text>
        <text x="495" y="62" fill="#a7f3d0" font-size="7.5" text-anchor="middle">Capture stdio</text>

        <path d="M 560 50 L 590 50" stroke="#34d399" stroke-width="1.5"/>

        <rect x="590" y="25" width="140" height="50" rx="4" fill="#1e1b4b" stroke="#a855f7"/>
        <text x="660" y="48" fill="#ffffff" font-size="8.5" font-weight="700" text-anchor="middle">5. Telemetry & TTS</text>
        <text x="660" y="62" fill="#e9d5ff" font-size="7.5" text-anchor="middle">Piper Voice Reply</text>
    </svg>
</div>

<h2>Workflow B: Autonomous Self-Healing on Execution Failure</h2>
<div class="card-grid-3 avoid-break">
    <div class="feature-card">
        <h4>1. Non-Zero Exit & Intercept</h4>
        <p><code>terminal_hook.rs</code> detects <code>exit_code != 0</code>. Raw stderr is piped to the <code>SelfHealingHook</code>.</p>
    </div>
    <div class="feature-card">
        <h4>2. Diagnosis & Patch Synthesis</h4>
        <p><code>TracebackAnalyzer</code> isolates the exception. Qwen 3:4B synthesizes a corrected script candidate.</p>
    </div>
    <div class="feature-card">
        <h4>3. 5s Countdown & Retest</h4>
        <p>The Slint dashboard displays an animated 5s modal. If uncancelled, the patch executes (capped at N=3 retries).</p>
    </div>
</div>

<h2>Workflow C: Hardware Overload & Graceful QLoRA Eviction</h2>
<div class="card-grid-3 avoid-break">
    <div class="feature-card">
        <h4>1. Hardware Ceiling Breach</h4>
        <p>The Rust monitor thread detects RAM > 12 GB or VRAM > 6 GB, writing <code>true</code> to <code>GLOBAL_SUSPEND_FLAG</code>.</p>
    </div>
    <div class="feature-card">
        <h4>2. VRAM Cache Purge</h4>
        <p><code>GovernorCallback</code> triggers <code>model.save_pretrained()</code>, runs <code>gc.collect()</code>, and clears CUDA cache.</p>
    </div>
    <div class="feature-card">
        <h4>3. Spin-Wait & Resumption</h4>
        <p>The training thread sleeps until resource levels return to safe limits, then resumes the SFT loop.</p>
    </div>
</div>

<div class="page-break"></div>

<!-- ═══════════════════════════════════════════════════════════════════════════ -->
<!-- CONFIGURATION & DEPLOYMENT GUIDE                                          -->
<!-- ═══════════════════════════════════════════════════════════════════════════ -->

<h1><span class="section-num">8</span> Configuration, Build & Deployment Guide</h1>

<p>
    AURIX is configured via a centralized, human-readable TOML configuration file (<code>config.toml</code>) 
    located in the project root.
</p>

<h2>`config.toml` Parameter Reference</h2>
<pre class="code-rust"><code># AURIX Desktop AI Agent — config.toml Specification
[security]
allowed_project_paths = [
    "G:/Websites By Ai/AURIX",
    "C:/Users/NAC/Documents/University/Projects"
]
file_jail_enabled = true
read_only_mode = false
trust_token_required = true

[resources]
max_ram_gb = 12.0               # Host RAM ceiling before governor triggers suspension
max_vram_gb = 6.0               # Discrete GPU VRAM ceiling (NVIDIA RTX 4060)
cpu_throttle_percent = 85.0     # CPU usage throttle threshold
poll_interval_ms = 1000         # Watchdog polling cadence
suspend_on_overload = true

[audio]
microphone = "Default"
whisper_model_path = "models/whisper/ggml-base.en.bin"
whisper_threads = 4
piper_model_path = "models/piper/en_US-lessac-medium.onnx"
piper_config_path = "models/piper/en_US-lessac-medium.onnx.json"
auto_tts_reply = true

[llm]
model_name = "unsloth/Qwen3-4B"
max_seq_length = 2048
load_in_4bit = true
quantization = "nf4"
device = "cuda"
temperature = 0.7
top_p = 0.9</code></pre>

<h2>Build & Execution Instructions</h2>

<h3>1. Compile the Core Rust Engine (PyO3 Extension)</h3>
<pre><code># Build the native Python extension module using Maturin
cd core_engine
maturin develop --release</code></pre>

<h3>2. Launch the Native Slint GUI Command Center</h3>
<pre><code># Launch via Python controller (binds AI engine + telemetry + Slint GUI)
python native_ui/run_ui.py

# Or run the standalone native Rust executable
cargo run --manifest-path native_ui/Cargo.toml --release</code></pre>

<h3>3. Run Continuous QLoRA Background Training</h3>
<pre><code># Start continuous training on local telemetry stream
python ai_engine/training/qlora_loop.py</code></pre>

<h3>4. Execute Verification Test Suite</h3>
<pre><code># Run full integration test suite across Python and Rust
pytest tests/
cargo test --workspace</code></pre>

<div class="callout callout-success avoid-break">
    <div class="callout-title">System Readiness Verification</div>
    The test suite in <code>tests/</code> validates all subsystems in isolation and end-to-end, including Qwen prompt formatting (<code>test_qwen_model.py</code>), governor limit tripwires (<code>test_governor_limits.rs</code>), file jail canonicalization (<code>test_file_jail.rs</code>), and data pipeline integration (<code>test_data_pipeline.py</code>).
</div>

</body>
</html>
"""

def generate_pdf():
    print("Writing intermediate HTML...")
    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        shutil.which("chrome"),
        shutil.which("google-chrome"),
        shutil.which("msedge"),
    ]
    
    browser_bin = None
    for p in chrome_paths:
        if p and os.path.exists(p):
            browser_bin = p
            break
            
    if not browser_bin:
        raise RuntimeError("No headless Chrome/Edge browser found to generate PDF.")
        
    print(f"Rendering PDF via {browser_bin}...")
    cmd = [
        browser_bin,
        "--headless",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--print-to-pdf={OUTPUT_PDF}",
        HTML_FILE
    ]
    
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Error rendering PDF: {res.stderr}")
        return False
        
    if os.path.exists(OUTPUT_PDF):
        size_kb = os.path.getsize(OUTPUT_PDF) / 1024
        print(f"SUCCESS: Generated PDF at {OUTPUT_PDF} ({size_kb:.1f} KB)")
        if os.path.exists(HTML_FILE):
            os.remove(HTML_FILE)
        return True
    else:
        print("PDF output file was not created.")
        return False

if __name__ == "__main__":
    generate_pdf()
