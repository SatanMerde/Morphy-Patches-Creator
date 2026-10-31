"""
Preset Recipes Catalog
Battle-tested patch templates for common Android reverse-engineering objectives.
"""
from typing import Dict, Any, List

RECIPES: Dict[str, Dict[str, Any]] = {
    "ad_removal": {
        "title": "Universal Ad Removal",
        "description": "Hooks major ad SDK initialization and display calls (AdMob, UnityAds, AppLovin).",
        "target_strings": ["com.google.android.gms.ads", "UnityAds", "com.applovin"],
        "target_opcodes": ["invoke-virtual", "move-result", "return-void"],
        "instructions": "return-void"
    },
    "allow_screenshots": {
        "title": "Allow Screenshots (FLAG_SECURE Bypass)",
        "description": "Clears WindowManager.LayoutParams.FLAG_SECURE (0x2000) to allow capturing protected screens.",
        "target_strings": ["setFlags", "FLAG_SECURE"],
        "target_opcodes": ["const/16", "invoke-virtual", "return-void"],
        "instructions": "return-void"
    },
    "amoled_black": {
        "title": "AMOLED Dark Theme",
        "description": "Forces pure black background styling by overriding dark mode color values to #000000.",
        "target_strings": ["isDarkModeEnabled", "dark_theme", "theme_mode"],
        "target_opcodes": ["invoke-virtual", "move-result", "return"],
        "instructions": "const/4 v0, 0x1\nreturn v0"
    },
    "root_check_bypass": {
        "title": "Root Detection Bypass",
        "description": "Neutralizes common su binary and test-keys root detection heuristics.",
        "target_strings": ["/system/bin/su", "/system/xbin/su", "which su", "test-keys"],
        "target_opcodes": ["invoke-virtual", "move-result", "return"],
        "instructions": "const/4 v0, 0x0\nreturn v0"
    },
    "vpn_check_bypass": {
        "title": "VPN / Proxy Detection Bypass",
        "description": "Spoofs network capability checks to indicate no active VPN or proxy.",
        "target_strings": ["TRANSPORT_VPN", "hasTransport"],
        "target_opcodes": ["invoke-virtual", "move-result", "return"],
        "instructions": "const/4 v0, 0x0\nreturn v0"
    }
}

class RecipeManager:
    """Manages built-in patch recipes and templates."""

    @staticmethod
    def list_recipes() -> List[Dict[str, Any]]:
        return [{"id": k, **v} for k, v in RECIPES.items()]

    @staticmethod
    def get_recipe(recipe_id: str) -> Dict[str, Any]:
        return RECIPES.get(recipe_id, {})
