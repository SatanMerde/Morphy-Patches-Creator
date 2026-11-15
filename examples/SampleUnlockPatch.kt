/*
 * Sample of the code Morphy Patches Creator generates.
 *
 * This is NOT hand-written demo output: it mirrors the structure produced by
 * morphy_creator/synthesizer/kotlin.py for a real target found by the analysis.
 *
 * API notes (Morphe Patcher, current):
 *  - a patch is a public top-level `val` created by patch(...)
 *  - there is no @Patch annotation and no replaceMethod
 *  - matching uses Fingerprint(...).match()
 *  - changes use returnEarly(...) or replaceInstruction(...)
 */

package app.morphe.patches.premium

import app.morphe.patcher.Fingerprint
import app.morphe.patcher.match
import app.morphe.patcher.patch.Compatibility
import app.morphe.patcher.patch.patch
import app.morphe.patcher.util.returnEarly

/** Unlocks local premium checks: the app's own entitlement methods answer "yes". */
@Suppress("unused")
val unlockPremiumPatch = patch(
    name = "Unlock premium / paid features",
    description = "Bypass local in-app purchase and subscription checks.",
    default = true,
) {
    compatibleWith(Compatibility("com.example.app", "app"))

    execute {
        // com.example.billing.BillingManager.isPremiumUser: always answer "yes"
        isPremiumUserFingerprint.match().method.returnEarly(true)
    }
}

private object isPremiumUserFingerprint : Fingerprint(
    definingClass = "Lcom/example/billing/BillingManager;",
    name = "isPremiumUser",
    returnType = "Z",
    parameters = listOf(),
    strings = listOf("INAPP_PURCHASE_ITEM_LIST"),
)
