# Getting started

## 1. Install

```powershell
git clone https://github.com/SatanMerde/Morphy-Patches-Creator.git
cd Morphy-Patches-Creator
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Linux / macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Requirements: **Python 3.10+**. Optional, only for the features that use them:

| Tool | Needed for | Install |
|---|---|---|
| JDK 17+ | compiling a real `.mpp` | [Adoptium Temurin](https://adoptium.net/) |
| Android SDK | the D8 step of the `.mpp` build | [Android Studio](https://developer.android.com/studio) or the command-line tools |
| Git | downloading the Morphe project template | [git-scm.com](https://git-scm.com/) |
| Apktool | `morphy-creator unpack` | [Apktool](https://github.com/iBotPeaches/Apktool) |
| JADX | `morphy-creator unpack` / Java view | [JADX](https://github.com/skylot/jadx) |

Run `morphy-creator doctor` to see what is missing. The SDK is found automatically when it sits in Android Studio's default folder; otherwise set `ANDROID_HOME`. The writer then fills in `local.properties` for you.

## 2. First patch

```powershell
morphy-creator
```

Answer the four questions. For a first try, choose a simple goal such as **Allow screenshots** on an app you own. You should see a small table of candidates with a confidence label, then a plan, then a confirmation prompt.

Output lands in `./morphy-output`:

- `src/` — generated Kotlin
- `dist/` — `.mpp` or `morphy-project.zip`
- `REPORT.txt` — what was found, why, and what to test

## 3. Compile the bundle

If `doctor` reports Java, Git and a registry token as OK:

```powershell
morphy-creator build .\morphy-output
```

The first run downloads Gradle and the Morphe plugin, so it takes several minutes. Later runs reuse the cache.

The token needs the **`read:packages`** scope on `github.com` (it is used to read
the MorpheApp packages, which belong to another organisation, so a fine-grained
token cannot work).

The quickest route if you already use the GitHub CLI:

```powershell
gh auth refresh -h github.com -s read:packages
gh auth token   # copy this value into gpr.key below
```

Or create a classic token at
`GitHub → Settings → Developer settings → Personal access tokens` with
**`read:packages`**, then add:

```properties
# %USERPROFILE%\.gradle\gradle.properties
gpr.user=your-github-username
gpr.key=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

`morphy-creator doctor` reads the scopes of the configured token and tells you
which one is missing, so you do not have to guess why Gradle answers 404/401.

## 4. Install on the phone

1. Copy the `.mpp` to the device.
2. Open Morphe Manager → import the bundle.
3. Select the app, apply the patch, reinstall when prompted.

Keep the original APK. Reinstalling it is the clean rollback.

## 5. If a goal finds nothing

- Try `morphy-creator inspect app.apk --details`: the report shows the evidence, or why nothing scored high enough.
- Run `morphy-creator investigate app.apk --goal "..." --details` to see each candidate ranked strong / moderate / weak. If every candidate is weak, the tool will not recommend a patch.
- **"SDK found, no hook"** means the app delegates that feature to a library and keeps no local check the tool trusts. Patching inside the SDK is deliberately avoided; try another goal.
- Use the **Something else** option (`a`) with a word you actually saw in the app — a menu label, an error message, a feature name. Custom search looks at method names, class names and text constants.
- Obfuscated apps (R8/ProGuard) hide names; the tool then relies on preference keys, SDK calls and literals, which is less precise.

## 6. Verify and share

```powershell
morphy-creator verify .\morphy-output\src\app\morphe\patches\screenshots\AllowScreenshotsPatch.kt
```

A score below 80 means a fragile fingerprint or a missing `compatibleWith(...)`; the message names the exact line to look at.
