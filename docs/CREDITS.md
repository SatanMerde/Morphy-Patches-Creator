# Credits

Morphy Patches Creator is an independent tool. It targets the Morphe ecosystem and optionally uses two excellent open-source decompilers.

## Morphe

- [MorpheApp/morphe-patcher](https://github.com/MorpheApp/morphe-patcher) — the patch API (`app.morphe.patcher`), fingerprinting, bundle loader.
- [MorpheApp/morphe-patches-template](https://github.com/MorpheApp/morphe-patches-template) — the project skeleton cloned by `PatchWriter`.
- [MorpheApp/morphe-patches-gradle-plugin](https://github.com/MorpheApp/morphe-patches-gradle-plugin) — `buildAndroid`, D8 packaging, manifest and signing.
- [MorpheApp/morphe-manager](https://github.com/MorpheApp/morphe-manager) — the on-device installer.

Generated code follows their current conventions: a public top-level `val ... = patch(...)`, `Fingerprint(...).match()`, `returnEarly(...)`, `replaceInstruction(...)` and `compatibleWith(Compatibility(...))`. There is no `@Patch` annotation and no `replaceMethod` in this API.

## Apktool

- Author: Connor Tumbleson ([@iBotPeaches](https://github.com/iBotPeaches)), original author Ryszard Wiśniewski ([@brutall](https://github.com/brutall))
- Repository: <https://github.com/iBotPeaches/Apktool>
- License: Apache 2.0
- Used for: optional `unpack` command (manifest, resources, smali). The analysis itself does not need it.

## JADX

- Author: [@skylot](https://github.com/skylot)
- Repository: <https://github.com/skylot/jadx>
- License: Apache 2.0
- Used for: optional Java source view through the MCP tool `morphe_decompile_java`.

## Python libraries

- [Click](https://click.palletsprojects.com/) — command line framework.
- [Rich](https://github.com/Textualize/rich) — terminal tables, panels and colours.

The DEX and AXML parsers are original code written for this project; no Android SDK, Androguard or dexlib2 is required at analysis time.
