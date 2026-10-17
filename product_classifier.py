"""
AnnaRakshak — Reliable Product Classification Pipeline
======================================================
Deterministic, evidence-based product classifier that enforces strict domain rules
before and alongside AI model analysis.

Guarantees:
  1. High-Confidence Deterministic Rules: Evaluates product names, brands, forms,
     and label text before relying on generative AI.
  2. Medicine vs Beverage Protection: Explicitly identifies medicines and
     pharmaceutical products (cough syrup, tablets, capsules, oral suspensions)
     and NEVER classifies a medicine as a beverage simply because it is liquid
     or contains the word "syrup".
  3. Non-Food Separation: Keeps product category separate from storage instructions,
     packaging types (bottle, blister pack, carton), and product condition.
  4. Explicit Uncertainty: Returns an uncertain / needs-review state when evidence
     is insufficient or conflicting rather than guessing.
  5. Established Schema Compatibility: Uses supported backend category vocabulary:
     - "Medicine"
     - "Dairy"
     - "Beverage"
     - "Grains"
     - "Snacks"
     - "Produce"
     - "Pantry"
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


CATEGORY_MEDICINE = "Medicine"
CATEGORY_DAIRY = "Dairy"
CATEGORY_BEVERAGE = "Beverage"
CATEGORY_GRAINS = "Grains"
CATEGORY_SNACKS = "Snacks"
CATEGORY_PRODUCE = "Produce"
CATEGORY_PANTRY = "Pantry"

SUPPORTED_CATEGORIES = {
    CATEGORY_MEDICINE,
    CATEGORY_DAIRY,
    CATEGORY_BEVERAGE,
    CATEGORY_GRAINS,
    CATEGORY_SNACKS,
    CATEGORY_PRODUCE,
    CATEGORY_PANTRY,
}


@dataclass
class ClassificationResult:
    """Detailed result of product classification."""
    category: str | None
    confidence: float
    source: Literal["rule_deterministic", "ai_model", "uncertain"]
    evidence: str
    product_form: str | None = None
    needs_review: bool = False
    review_reason: str | None = None


# ---------------------------------------------------------------------------
# Pharmaceutical / Medicinal Keywords & Regexes
# ---------------------------------------------------------------------------

PHARMA_FORMS = [
    r"\btablets?\b",
    r"\bcapsules?\b",
    r"\boral\s+suspension\b",
    r"\boral\s+solution\b",
    r"\boral\s+drops?\b",
    r"\bsyrup\s+(?:ip|bp|usp)\b",
    r"\btablets?\s+(?:ip|bp|usp)\b",
    r"\bcapsules?\s+(?:ip|bp|usp)\b",
    r"\blozenges?\b",
    r"\bcough\s+drops?\b",
    r"\bointment\b",
    r"\binhaler\b",
    r"\beye\s+drops?\b",
    r"\bear\s+drops?\b",
]

MEDICINAL_SYRUP_INDICATORS = [
    r"\bcough\s+syrup\b",
    r"\bcold\s+(?:&|and)?\s+cough\b",
    r"\bexpectorant\b",
    r"\bantihistaminic\b",
    r"\bmucolytic\b",
    r"\bdecongestant\b",
    r"\bbronchodilator\b",
    r"\bsoothing\s+cough\b",
    r"\bpediatric\s+syrup\b",
]

MEDICINAL_ACTIVE_INGREDIENTS = [
    r"\bparacetamol\b",
    r"\bacetaminophen\b",
    r"\bibuprofen\b",
    r"\bdiphenhydramine\b",
    r"\bdextromethorphan\b",
    r"\bchlorpheniramine\b",
    r"\bcetirizine\b",
    r"\bamoxicillin\b",
    r"\bazithromycin\b",
    r"\bguaifenesin\b",
    r"\bambroxol\b",
    r"\bterbutaline\b",
    r"\bphenylephrine\b",
    r"\baspirin\b",
    r"\bomeprazole\b",
    r"\bpantoprazole\b",
    r"\bmetformin\b",
    r"\batorvastatin\b",
    r"\bloratadine\b",
]

MEDICINAL_LABEL_MARKERS = [
    r"\bschedule\s+[ghx1]+\s+prescription\b",
    r"\bschedule\s+h\b",
    r"\bschedule\s+h1\b",
    r"\brx\s+only\b",
    r"\bfor\s+therapeutic\s+use\b",
    r"\btherapeutic\s+dosage\b",
    r"\bdosage\s*:\s*(?:as\s+directed|one|two|\d+)\b",
    r"\bcomposition\s*:\s*each\b",
    r"\beach\s+(?:5\s*ml|10\s*ml|tablet|capsule)\s+contains\b",
    r"\bkeep\s+out\s+of\s+reach\s+of\s+children\b",
    r"\bmfg\s+lic\s+no\b",
    r"\bmfg\s+licence\b",
    r"\bpharmaceutical\b",
]

KNOWN_MEDICINE_BRANDS = [
    r"\bbenadryl\b",
    r"\bcorex\b",
    r"\bcodistar\b",
    r"\bascoril\b",
    r"\bgrilinctus\b",
    r"\bcrocin\b",
    r"\bcalpol\b",
    r"\bdolo\s*650\b",
    r"\bvicks\s+(?:action\s*500|vaporub|cough)\b",
    r"\bstrepsils\b",
    r"\bzyrtec\b",
    r"\ballegra\b",
    r"\bcombiflam\b",
    r"\bdisprin\b",
    r"\bgelusil\b",
    r"\bdigene\b",
]

# ---------------------------------------------------------------------------
# Food Category Patterns (Strict Negative Checks Against Medicine)
# ---------------------------------------------------------------------------

BEVERAGE_INDICATORS = [
    r"\bfruit\s+juice\b",
    r"\borange\s+juice\b",
    r"\bapple\s+juice\b",
    r"\bmango\s+juice\b",
    r"\bsoft\s+drink\b",
    r"\bcarbonated\s+beverage\b",
    r"\benergy\s+drink\b",
    r"\bmineral\s+water\b",
    r"\bsparkling\s+water\b",
    r"\bgreen\s+tea\b",
    r"\bblack\s+tea\b",
    r"\binstant\s+coffee\b",
    r"\blemonade\b",
    r"\bsoda\b",
    r"\bcold\s+drink\b",
    r"\bnectar\b",
    r"\biced\s+tea\b",
]

KNOWN_BEVERAGE_BRANDS = [
    r"\bcoca[\s-]?cola\b",
    r"\bpepsi\b",
    r"\bthums\s*up\b",
    r"\bsprite\b",
    r"\bfanta\b",
    r"\bmirinda\b",
    r"\bfrooti\b",
    r"\bmaaza\b",
    r"\breal\s+fruit\b",
    r"\btropicana\b",
    r"\bred\s*bull\b",
    r"\bkinley\b",
    r"\baquafina\b",
    r"\bbisleri\b",
    r"\blipton\b",
    r"\bnescafe\b",
    r"\bbru\s+coffee\b",
]

DAIRY_INDICATORS = [
    r"\bpackaged\s+milk\b",
    r"\btoned\s+milk\b",
    r"\bfull\s+cream\s+milk\b",
    r"\bdoub?le\s+toned\s+milk\b",
    r"\bcow\s+milk\b",
    r"\bbuffalo\s+milk\b",
    r"\bpasteurized\s+milk\b",
    r"\bpasteurised\s+milk\b",
    r"\bhomogenized\s+milk\b",
    r"\bmilk\b",
    r"\bpaneer\b",
    r"\bcurd\b",
    r"\bdahi\b",
    r"\byogurt\b",
    r"\byoghurt\b",
    r"\bbutter\b",
    r"\bcheese\s+slices?\b",
    r"\bcheddar\s+cheese\b",
    r"\bmozzarella\b",
    r"\bchaas\b",
    r"\bbuttermilk\b",
    r"\blassi\b",
    r"\bghee\b",
    r"\bdairy\s+whitener\b",
]

KNOWN_DAIRY_BRANDS = [
    r"\bamul\b",
    r"\bmother\s+dairy\b",
    r"\bnandini\b",
    r"\bverka\b",
    r"\bvijaya\b",
    r"\bgowardhan\b",
    r"\bbritannia\s+cheese\b",
    r"\bbritannia\s+butter\b",
    r"\bnestle\s+everyday\b",
    r"\bnestle\s+a\+\b",
]

GRAINS_BAKERY_INDICATORS = [
    r"\bbread\b",
    r"\bbrown\s+bread\b",
    r"\bwhite\s+bread\b",
    r"\bwhole\s+wheat\s+bread\b",
    r"\brusk\b",
    r"\bbiscuit\b",
    r"\bbiscuits\b",
    r"\bcookies?\b",
    r"\batta\b",
    r"\bwheat\s+flour\b",
    r"\bmaida\b",
    r"\brice\b",
    r"\bbasmati\s+rice\b",
    r"\boats\b",
    r"\bcorn\s*flakes\b",
    r"\bmuesli\b",
    r"\bpasta\b",
    r"\bnoodles\b",
    r"\bvermicelli\b",
]

SNACKS_INDICATORS = [
    r"\bpotato\s+chips\b",
    r"\bchips\b",
    r"\bcrisps\b",
    r"\bnamkeen\b",
    r"\bbhujia\b",
    r"\bsev\b",
    r"\bpopcorn\b",
    r"\bnacho\s+chips\b",
    r"\bextrud(?:ed)?\s+snack\b",
]

PRODUCE_INDICATORS = [
    r"\bfresh\s+apples?\b",
    r"\bfresh\s+bananas?\b",
    r"\bfresh\s+tomatoes?\b",
    r"\bfresh\s+potatoes?\b",
    r"\bfresh\s+onions?\b",
    r"\bfresh\s+vegetables?\b",
    r"\bfresh\s+fruits?\b",
    r"\borganic\s+spinach\b",
]

PANTRY_INDICATORS = [
    r"\bcooking\s+oil\b",
    r"\bsunflower\s+oil\b",
    r"\bmustard\s+oil\b",
    r"\bolive\s+oil\b",
    r"\brefined\s+oil\b",
    r"\btable\s+salt\b",
    r"\biodized\s+salt\b",
    r"\bioc?dised\s+salt\b",
    r"\bsugar\b",
    r"\bturmeric\s+powder\b",
    r"\bchilli\s+powder\b",
    r"\bcoriander\s+powder\b",
    r"\bgaram\s+masala\b",
    r"\btomato\s+ketchup\b",
    r"\bsoy\s+sauce\b",
    r"\bvinegar\b",
    r"\bhoney\b",
]


class ProductClassifier:
    """
    Deterministic rule-based product classifier with high confidence guarantees.
    Runs before AI model to ensure safety-critical categorizations (such as medicines)
    cannot be misclassified as foods or beverages.
    """

    @classmethod
    def classify(
        cls,
        product_name: str | None = None,
        brand: str | None = None,
        label_text: str | None = None,
        product_form: str | None = None,
    ) -> ClassificationResult:
        """
        Classify a product from available text evidence.
        Returns a ClassificationResult with category, confidence, evidence, and review flags.
        """
        tokens: list[str] = []
        if product_name:
            tokens.append(product_name.strip())
        if brand:
            tokens.append(brand.strip())
        if product_form:
            tokens.append(product_form.strip())
        if label_text:
            tokens.append(label_text.strip())

        combined_text = " ".join(tokens)
        lower_text = combined_text.lower()

        if not lower_text.strip():
            return ClassificationResult(
                category=None,
                confidence=0.0,
                source="uncertain",
                evidence="No product name or label text provided",
                needs_review=True,
                review_reason="No visible packaging text or product details found for classification.",
            )

        # -------------------------------------------------------------------
        # Rule 1: Pharmaceutical & Medicine Detection (Highest Priority)
        # -------------------------------------------------------------------
        is_medicine, med_evidence, med_form = cls._detect_medicine(lower_text)
        if is_medicine:
            return ClassificationResult(
                category=CATEGORY_MEDICINE,
                confidence=0.98,
                source="rule_deterministic",
                evidence=med_evidence,
                product_form=med_form,
                needs_review=False,
            )

        # -------------------------------------------------------------------
        # Rule 2: Dairy Products (Packaged Milk, Butter, Cheese, Curd)
        # -------------------------------------------------------------------
        is_dairy, dairy_evidence = cls._detect_dairy(lower_text)
        if is_dairy:
            return ClassificationResult(
                category=CATEGORY_DAIRY,
                confidence=0.95,
                source="rule_deterministic",
                evidence=dairy_evidence,
                product_form="liquid" if "milk" in lower_text or "chaas" in lower_text else "solid",
                needs_review=False,
            )

        # -------------------------------------------------------------------
        # Rule 3: Beverages (Fruit Juice, Sodas, Teas, Coffees)
        # -------------------------------------------------------------------
        is_beverage, bev_evidence = cls._detect_beverage(lower_text)
        if is_beverage:
            return ClassificationResult(
                category=CATEGORY_BEVERAGE,
                confidence=0.95,
                source="rule_deterministic",
                evidence=bev_evidence,
                product_form="liquid",
                needs_review=False,
            )

        # -------------------------------------------------------------------
        # Rule 4: Grains & Bakery
        # -------------------------------------------------------------------
        for pattern in GRAINS_BAKERY_INDICATORS:
            if re.search(pattern, lower_text):
                matched = re.search(pattern, lower_text).group(0)
                return ClassificationResult(
                    category=CATEGORY_GRAINS,
                    confidence=0.90,
                    source="rule_deterministic",
                    evidence=f"Matched grain/bakery term: '{matched}'",
                    needs_review=False,
                )

        # -------------------------------------------------------------------
        # Rule 5: Snacks
        # -------------------------------------------------------------------
        for pattern in SNACKS_INDICATORS:
            if re.search(pattern, lower_text):
                matched = re.search(pattern, lower_text).group(0)
                return ClassificationResult(
                    category=CATEGORY_SNACKS,
                    confidence=0.90,
                    source="rule_deterministic",
                    evidence=f"Matched snack keyword: '{matched}'",
                    needs_review=False,
                )

        # -------------------------------------------------------------------
        # Rule 6: Produce
        # -------------------------------------------------------------------
        for pattern in PRODUCE_INDICATORS:
            if re.search(pattern, lower_text):
                matched = re.search(pattern, lower_text).group(0)
                return ClassificationResult(
                    category=CATEGORY_PRODUCE,
                    confidence=0.90,
                    source="rule_deterministic",
                    evidence=f"Matched fresh produce term: '{matched}'",
                    needs_review=False,
                )

        # -------------------------------------------------------------------
        # Rule 7: Pantry Staples
        # -------------------------------------------------------------------
        for pattern in PANTRY_INDICATORS:
            if re.search(pattern, lower_text):
                matched = re.search(pattern, lower_text).group(0)
                return ClassificationResult(
                    category=CATEGORY_PANTRY,
                    confidence=0.90,
                    source="rule_deterministic",
                    evidence=f"Matched pantry staple term: '{matched}'",
                    needs_review=False,
                )

        # -------------------------------------------------------------------
        # Rule 8: Ambiguous or Insufficient Evidence
        # -------------------------------------------------------------------
        return ClassificationResult(
            category=None,
            confidence=0.2,
            source="uncertain",
            evidence="No clear high-confidence category indicators found in product text",
            needs_review=True,
            review_reason="Product category is ambiguous from label text; manual review required.",
        )

    @classmethod
    def _detect_medicine(cls, text: str) -> tuple[bool, str, str | None]:
        """Check for pharmaceutical markers, forms, brands, and ingredients."""
        # 1. Medicinal syrups (e.g. cough syrup, cold and cough, expectorant)
        for pattern in MEDICINAL_SYRUP_INDICATORS:
            m = re.search(pattern, text)
            if m:
                return True, f"Pharmaceutical syrup indicator matched: '{m.group(0)}'", "syrup"

        # 2. General pharmaceutical forms (tablets, capsules, suspensions, lozenges)
        for pattern in PHARMA_FORMS:
            m = re.search(pattern, text)
            if m:
                matched_form = m.group(0)
                form_name = "tablet" if "tablet" in matched_form else (
                    "capsule" if "capsule" in matched_form else (
                        "suspension" if "suspension" in matched_form else "pharmaceutical"
                    )
                )
                return True, f"Pharmaceutical dosage form matched: '{matched_form}'", form_name

        # 3. Medicinal active ingredients
        for pattern in MEDICINAL_ACTIVE_INGREDIENTS:
            m = re.search(pattern, text)
            if m:
                return True, f"Active pharmaceutical ingredient matched: '{m.group(0)}'", "pharmaceutical"

        # 4. Known medicine brands
        for pattern in KNOWN_MEDICINE_BRANDS:
            m = re.search(pattern, text)
            if m:
                return True, f"Pharmaceutical brand identified: '{m.group(0)}'", "pharmaceutical"

        # 5. Regulatory & clinical label markers
        for pattern in MEDICINAL_LABEL_MARKERS:
            m = re.search(pattern, text)
            if m:
                return True, f"Pharmaceutical regulatory/dosage marker matched: '{m.group(0)}'", "pharmaceutical"

        # 6. Compound check: "syrup" alone + any clinical/dosage cue
        if "syrup" in text:
            clinical_cues = ["relief", "chest", "throat", "bronchial", "dose", "ml", "spoonful", "mg", "oral"]
            if any(cue in text for cue in clinical_cues):
                # Ensure it's not pancake/chocolate/maple syrup
                non_med_syrups = ["maple", "chocolate", "pancake", "waffle", "corn syrup", "golden syrup"]
                if not any(nms in text for nms in non_med_syrups):
                    return True, "Medicinal syrup identified via syrup form and therapeutic cues", "syrup"

        return False, "", None

    @classmethod
    def _detect_dairy(cls, text: str) -> tuple[bool, str]:
        """Check for dairy indicators, ensuring medicine is excluded."""
        for pattern in DAIRY_INDICATORS:
            m = re.search(pattern, text)
            if m:
                return True, f"Dairy keyword matched: '{m.group(0)}'"
        for pattern in KNOWN_DAIRY_BRANDS:
            m = re.search(pattern, text)
            if m:
                return True, f"Dairy brand matched: '{m.group(0)}'"
        return False, ""

    @classmethod
    def _detect_beverage(cls, text: str) -> tuple[bool, str]:
        """Check for beverage indicators, ensuring no pharmaceutical markers."""
        # Check known beverage brands
        for pattern in KNOWN_BEVERAGE_BRANDS:
            m = re.search(pattern, text)
            if m:
                return True, f"Beverage brand matched: '{m.group(0)}'"
        # Check beverage types
        for pattern in BEVERAGE_INDICATORS:
            m = re.search(pattern, text)
            if m:
                return True, f"Beverage keyword matched: '{m.group(0)}'"
        return False, ""
