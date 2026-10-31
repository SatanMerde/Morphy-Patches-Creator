# 🏗️ Morphy Patches Creator Architecture

This document describes the engineering design and inter-process data flow of Morphy Patches Creator.

```mermaid
graph TD
    APK[Input APK / APKM] --> Ingestion[Phase 1: Ingestion & Extraction]
    
    subgraph Phase 1: Apktool Bridge
        Ingestion --> AXML[Decoded AndroidManifest.xml]
        Ingestion --> RES[Resource Table & ARSC Values]
        Ingestion --> SMALI[Disassembled Smali Files]
    end

    subgraph Phase 2: REA Inspection Engine
        APK --> SO[Native .so Libraries]
        SO --> REA_SYM[Symbol & XRef Extraction]
        SO --> REA_JNI[JNI Export Table & Native Hooks]
        SMALI --> REA_CORR[Static & Runtime Correlation]
    end

    subgraph Phase 3: Morphe-AI Cognitive Synthesizer
        AXML & RES & SMALI & REA_SYM & REA_JNI --> SYNTH[Pattern Analysis & Intent Identification]
        SYNTH --> FP[Resilient Fingerprint Generation]
        SYNTH --> AST_MOD[Bytecode AST Transformation Rules]
        SYNTH --> KT_GEN[Kotlin Patch Code Generation]
    end

    subgraph Phase 4: Verification & Build
        KT_GEN --> DRYRUN[Dry-Run Simulation on AST]
        DRYRUN --> GRADLE[Gradle Kotlin Compilation]
        GRADLE --> MPP[.mpp Morphe Patch Bundle]
    end
```

## Component Breakdown

### 1. Ingestion Bridge (`morphy_creator/adapters/apktool_adapter.py`)
- Wraps the Apktool execution environment.
- Handles split APK reconstitution (APKM/APKS to unified structure).
- Decodes resources while preserving XML namespaces and original resource IDs.

### 2. Binary Introspection Core (`morphy_creator/adapters/rea_adapter.py`)
- Communicates with REA tools via JSON-RPC / MCP protocols.
- Extracts symbol tables from native shared objects (`lib*.so`).
- Maps JNI function signatures to Java/Kotlin native method declarations.
- Identifies cryptographic routines, integrity checks, and billing verification flows.

### 3. Cognitive Synthesizer (`morphy_creator/synthesizer/`)
- Inspired by Morphe-AI.
- Computes opcode fingerprints that ignore variable register allocations and obfuscated class/method names.
- Renders typed Kotlin Morphe patches inheriting from `BytecodePatch`, `ResourcePatch`, or `SettingsPatch`.

### 4. Pipeline Engine (`morphy_creator/core/pipeline.py`)
- Orchestrates caching, intermediate artifact management, dry-run testing, and invocation of the Gradle compiler to generate `.mpp` archives.
