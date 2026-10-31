# 🚀 Getting Started with Morphy Patches Creator

## Installation

```bash
# 1. Clone repository
git clone https://github.com/SatanMerde/Morphy-Patches-Creator.git
cd Morphy-Patches-Creator

# 2. Setup virtual environment
python -m venv venv
# Linux/macOS:
source venv/bin/activate
# Windows:
.\venv\Scripts\activate

# 3. Install in editable mode
pip install -e .
```

## 5-Minute Tutorial: Creating Your First Patch

### Step 1: Unpack Target APK
```bash
morphy-creator unpack app.apk -o ./workspace/target_app
```

### Step 2: Analyze Native & Smali Patterns
```bash
morphy-creator inspect ./workspace/target_app --keyword "isPremium"
```

### Step 3: Synthesize Patch
```bash
morphy-creator synthesize ./workspace/target_app \
    --type unlock \
    --target-feature "isPremium" \
    --output ./patches/MyFirstPatch.kt
```

### Step 4: Verify and Build
```bash
morphy-creator build ./patches -o ./build/patches.mpp
```
