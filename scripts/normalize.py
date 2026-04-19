"""
Text normalization library for SMP OCR project.

Handles:
- De-hyphenation of line wraps
- Language-specific OCR fixes (DE/EN/FR)
- Stock number spacing repair
- Known substitutions
- Logging all changes for audit trail

Usage:
    from normalize import normalize_text, NormalizationLog

    log = NormalizationLog()
    cleaned = normalize_text(raw_text, language='de', log=log, context="band-1/p0042")
    log.write_to_file("rs_smp_corpus/index/normalization_log.md")
"""

import re
from pathlib import Path


class NormalizationLog:
    """Tracks all normalization changes for audit trail."""

    def __init__(self) -> None:
        self.entries: list[dict[str, str]] = []

    def add(self, original: str, normalized: str, rule: str, context: str = "") -> None:
        """Record a normalization change."""
        if original != normalized:
            self.entries.append(
                {
                    "context": context,
                    "rule": rule,
                    "original": original,
                    "normalized": normalized,
                }
            )

    def write_to_file(self, filepath: Path) -> None:
        """Write log to markdown file."""
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("# Normalization Log\n\n")
            f.write("All text substitutions applied during OCR processing.\n\n")
            f.write(f"Total changes: {len(self.entries)}\n\n")

            # Group by rule
            by_rule: dict[str, list[dict[str, str]]] = {}
            for entry in self.entries:
                rule = entry["rule"]
                if rule not in by_rule:
                    by_rule[rule] = []
                by_rule[rule].append(entry)

            for rule, changes in sorted(by_rule.items()):
                f.write(f"\n## {rule}\n\n")
                f.write(f"{len(changes)} occurrences\n\n")

                # Show first 20 examples
                for change in changes[:20]:
                    ctx = f" [{change['context']}]" if change["context"] else ""
                    f.write(
                        f"- `{change['original']}` → `{change['normalized']}`{ctx}\n"
                    )

                if len(changes) > 20:
                    f.write(f"\n... and {len(changes) - 20} more\n")


# Language-agnostic punctuation / whitespace artifacts leaked by the OCR
# pipeline (CJK fullwidth forms, invisible whitespace). Always wrong in
# German/English/French technical prose.
GENERIC_SUBSTITUTIONS = {
    "\uff0c": ",",  # fullwidth comma
    "\uff0e": ".",  # fullwidth period
    "\u3000": " ",  # ideographic space
    "\u200b": "",  # zero-width space
    "\u00ad": "",  # soft hyphen
}

# German OCR corrections
DE_SUBSTITUTIONS = {
    # OCR artifacts
    "MeBtechnik": "Meßtechnik",
    "MeStechnik": "Meßtechnik",
    "Schliüssel": "Schlüssel",
    "BauelementeliBte": "Bauelementeliste",
    "Bauele-\nmente": "Bauelemente",
    # Common OCR misreads
    "Schaltungsbe-\nschreibung": "Schaltungsbeschreibung",
    "Funktions-\nprüfung": "Funktionsprüfung",
    "Instand-\nsetzung": "Instandsetzung",
    "Betriebs-\nvorbereitung": "Betriebsvorbereitung",
    # Technical terms
    "Signalgene-\nrator": "Signalgenerator",
    "Mikrowel-\nlen": "Mikrowellen",
    # Missing umlauts on R&S-specific verbs that appear as section
    # headings and in spec tables (~126 confirmed occurrences). Applied
    # via substring match; variants without the umlaut are not valid
    # German elsewhere in this corpus, so collisions are negligible.
    "Prufen": "Prüfen",
    "prufen": "prüfen",
    "gepruft": "geprüft",
}

# DE-strict umlaut restoration. Applied only to pages whose language is
# pure ``de`` (never ``de+en``) so ambiguous tokens like English ``fur``
# cannot be touched in bilingual contexts. Using regex word boundaries
# because substring replacement would also hit ``Furnier``, ``furchen``
# or ``aufklonnen`` etc.
DE_REGEX_SUBSTITUTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bfur\b"), "für"),
    (re.compile(r"\bKonnen\b"), "Können"),
    (re.compile(r"\bkonnen\b"), "können"),
    (re.compile(r"\bgemass\b"), "gemäß"),
]

# SI unit case fix: OCR occasionally upper-cases entire frequency units.
# R&S writes ``kHz``/``MHz``/``GHz``; never ``KHZ``/``MHZ``/``GHZ``. The
# leading lookbehind rejects matches inside all-caps acronyms while still
# firing on the common ``<digit>MHZ`` form.
HZ_UNIT_RE = re.compile(r"(?<![A-Za-z])([kKmMgG])HZ\b")

# Micro-prefix units written without the mu sign: ``9us``, ``100uV``,
# ``2uA`` etc. Trigger only when preceded by a digit to avoid matching
# the English pronoun "us" or unrelated identifiers.
MICRO_UNIT_RE = re.compile(r"(\d)(u)(s|V|A|F|H|W)\b")

# VLM OCR misrendering of the registered-sign ``®`` as U+00B8 cedilla
# directly before R&S product codes (``¸SMP02``, ``¸FSEA``, ``¸NRP``).  # noqa: RUF003
# All 69 corpus occurrences are followed by two or more uppercase letters,
# so the guard rejects stray legitimate cedilla usage.
CEDILLA_AS_R_SYMBOL_RE = re.compile(r"\u00B8(?=[A-Z]{2})")

# English OCR corrections
EN_SUBSTITUTIONS = {
    # OCR artifacts
    "perfor-\nmance": "performance",
    "adjust-\nment": "adjustment",
    "measure-\nment": "measurement",
    # Common misreads
    "Ievel": "level",
    "frequen-\ncy": "frequency",
    "synthe-\nsis": "synthesis",
}

# French OCR corrections (minimal - mostly in boilerplate)
FR_SUBSTITUTIONS = {
    "descrip-\ntion": "description",
    "spécifica-\ntion": "spécification",
}

# Stock number patterns
STOCK_NUMBER_PATTERNS = [
    # Fix spacing in stock numbers: "1038. 7344.01" → "1038.7344.01"
    (r"(\d{4})\.\s+(\d{4})\.(\d{2})", r"\1.\2.\3"),
    # Multiple models: "1035.5005.02/03/04/22" (keep as-is, just verify format)
    (r"(\d{4}\.\d{4}\.\d{2}(?:/\d{2})*)", r"\1"),
]


def dehyphenate_text(text: str, language: str = "de") -> str:
    """
    Remove line-wrap hyphenation.

    German: Bauele-\nmente → Bauelemente
    English: perfor-\nmance → performance

    Args:
        text: Text with potential hyphenation
        language: Language code for language-specific rules

    Returns:
        Text with hyphenation removed
    """
    # Pattern: word-part, hyphen, newline, word-part
    # But NOT for actual compound words (keep those hyphens)

    # Simple approach: remove hyphen+newline when followed by lowercase
    pattern = r"(\w+)-\n(\w+)"

    def replacer(match: re.Match[str]) -> str:
        before = match.group(1)
        after = match.group(2)
        # If the part after newline starts with lowercase, it's likely a wrap
        if after[0].islower():
            return before + after
        else:
            # Keep hyphen for compound words
            return before + "-" + after

    return re.sub(pattern, replacer, text)


def fix_stock_numbers(
    text: str, log: NormalizationLog | None = None, context: str = ""
) -> str:
    """Fix spacing and format issues in stock numbers."""
    result = text

    for pattern, replacement in STOCK_NUMBER_PATTERNS:
        new_result = re.sub(pattern, replacement, result)
        if new_result != result and log:
            # Find what changed
            log.add(result, new_result, "stock_number_spacing", context)
        result = new_result

    return result


def remove_cid_artifacts(
    text: str, log: NormalizationLog | None = None, context: str = ""
) -> str:
    """Remove (cid:NNNN) artifacts from OCR."""
    pattern = r"\(cid:\d+\)"
    cleaned = re.sub(pattern, "", text)

    if cleaned != text and log:
        log.add(text, cleaned, "remove_cid", context)

    return cleaned


def fix_hz_unit_case(
    text: str, log: NormalizationLog | None = None, context: str = ""
) -> str:
    """Normalize frequency unit casing: ``KHZ`` → ``kHz``, ``MHZ`` → ``MHz``,
    ``GHZ`` → ``GHz``."""

    def _repl(m: re.Match[str]) -> str:
        prefix = m.group(1)
        # k is lowercase; M and G are uppercase in SI.
        prefix_canonical = "k" if prefix.lower() == "k" else prefix.upper()
        return f"{prefix_canonical}Hz"

    cleaned = HZ_UNIT_RE.sub(_repl, text)
    if cleaned != text and log:
        log.add("(k|M|G)HZ", "(k|M|G)Hz", "hz_unit_case", context)
    return cleaned


def fix_micro_units(
    text: str, log: NormalizationLog | None = None, context: str = ""
) -> str:
    """Insert the micro sign for unit abbreviations OCR'd as plain ``u``:
    ``9us`` → ``9 µs``, ``100uV`` → ``100 µV``. Requires a preceding digit
    so English "us" pronouns aren't touched."""

    def _repl(m: re.Match[str]) -> str:
        return f"{m.group(1)} \u00b5{m.group(3)}"

    cleaned = MICRO_UNIT_RE.sub(_repl, text)
    if cleaned != text and log:
        log.add("<d>u<UNIT>", "<d> \u00b5<UNIT>", "micro_unit_sign", context)
    return cleaned


def fix_cedilla_as_r_symbol(
    text: str, log: NormalizationLog | None = None, context: str = ""
) -> str:
    """Restore the ``®`` sign lost by the VLM before R&S product codes
    (``¸SMP02`` → ``®SMP02``)."""  # noqa: RUF002
    cleaned = CEDILLA_AS_R_SYMBOL_RE.sub("\u00ae", text)
    if cleaned != text and log:
        log.add("\u00b8<CODE>", "\u00ae<CODE>", "cedilla_as_r_symbol", context)
    return cleaned


def apply_substitutions(
    text: str,
    substitutions: dict[str, str],
    rule_name: str,
    log: NormalizationLog | None = None,
    context: str = "",
) -> str:
    """Apply a dictionary of substitutions with logging."""
    result = text

    for original, replacement in substitutions.items():
        if original in result:
            result = result.replace(original, replacement)
            if log:
                log.add(original, replacement, rule_name, context)

    return result


def apply_regex_substitutions(
    text: str,
    rules: list[tuple[re.Pattern[str], str]],
    rule_name: str,
    log: NormalizationLog | None = None,
    context: str = "",
) -> str:
    """Apply word-boundary regex substitutions with logging. One log entry
    is emitted per pattern that changed something (not per occurrence)."""
    result = text
    for pattern, replacement in rules:
        new_result = pattern.sub(replacement, result)
        if new_result != result:
            if log:
                log.add(pattern.pattern, replacement, rule_name, context)
            result = new_result
    return result


def normalize_text(
    text: str,
    language: str = "de",
    log: NormalizationLog | None = None,
    context: str = "",
) -> str:
    """
    Apply all normalization steps to text.

    Args:
        text: Raw OCR text
        language: Language code ('de', 'en', 'fr', 'de+en')
        log: Optional log to record changes
        context: Context string for logging (e.g., "band-1/p0042")

    Returns:
        Normalized text
    """
    if not text:
        return text

    result = text

    # Step 1: Remove CID artifacts
    result = remove_cid_artifacts(result, log, context)

    # Step 2: Strip language-agnostic OCR noise (fullwidth punctuation,
    # zero-width spaces, soft hyphens). Runs before regex-based steps so
    # downstream patterns operate on clean ASCII punctuation.
    result = apply_substitutions(
        result, GENERIC_SUBSTITUTIONS, "generic_punctuation", log, context
    )

    # Step 3: Fix stock numbers
    result = fix_stock_numbers(result, log, context)

    # Step 4: De-hyphenate line wraps
    dehyphenated = dehyphenate_text(result, language)
    if dehyphenated != result and log:
        log.add(result, dehyphenated, "dehyphenation", context)
    result = dehyphenated

    # Step 5: Apply language-specific substitutions
    if "de" in language.lower():
        result = apply_substitutions(
            result, DE_SUBSTITUTIONS, "de_ocr_fixes", log, context
        )

    if "en" in language.lower():
        result = apply_substitutions(
            result, EN_SUBSTITUTIONS, "en_ocr_fixes", log, context
        )

    if "fr" in language.lower():
        result = apply_substitutions(
            result, FR_SUBSTITUTIONS, "fr_ocr_fixes", log, context
        )

    # Step 6: DE-strict umlaut restoration. Pure-German pages only to
    # prevent collisions with tokens that happen to be valid English
    # (``fur``) or appear inside bilingual captions.
    if language.lower() == "de":
        result = apply_regex_substitutions(
            result, DE_REGEX_SUBSTITUTIONS, "de_strict_umlaut", log, context
        )

    # Step 7: SI unit canonicalisation (language-agnostic).
    result = fix_hz_unit_case(result, log, context)
    result = fix_micro_units(result, log, context)

    # Step 8: VLM glyph recovery (language-agnostic).
    result = fix_cedilla_as_r_symbol(result, log, context)

    return result


def normalize_designator(designator: str) -> str | None:
    """
    Normalize component designator (R117, C42, V3, etc.).

    Returns None if the string doesn't look like a valid designator.
    """
    # Pattern: Letter(s) followed by digits, optional suffix
    match = re.match(r"^([A-Z]+)(\d+)([A-Z-]*)$", designator.strip().upper())
    if match:
        prefix, number, suffix = match.groups()
        return f"{prefix}{number}{suffix}"
    return None


def normalize_stock_number(stock: str) -> str | None:
    """
    Normalize stock number format.

    Examples:
        "1038.7344.01" → "1038.7344.01"
        "1035.5005.02/03/04/22" → "1035.5005.02/03/04/22"
        "1038. 7344.01" → "1038.7344.01"

    Returns None if the string doesn't look like a valid stock number.
    """
    # Remove spaces
    cleaned = stock.replace(" ", "")

    # Pattern: NNNN.NNNN.NN with optional /NN/NN/NN suffix
    pattern = r"^(\d{4})\.(\d{4})\.(\d{2})(?:/\d{2})*$"
    match = re.match(pattern, cleaned)

    if match:
        return cleaned

    return None


# Self-test function (called with --test flag)
def run_tests() -> bool:
    """Run self-tests on normalization functions."""
    print("Running normalize.py self-tests...")

    tests_passed = 0
    tests_failed = 0

    # Test 1: De-hyphenation
    test_text = "Bauele-\nmente sind wichtig"
    expected = "Bauelemente sind wichtig"
    result = dehyphenate_text(test_text, "de")
    if result == expected:
        print("✓ De-hyphenation: PASS")
        tests_passed += 1
    else:
        print(f"✗ De-hyphenation: FAIL (got '{result}')")
        tests_failed += 1

    # Test 2: Stock number spacing
    test_text = "Stock: 1038. 7344.01"
    log = NormalizationLog()
    result = normalize_text(test_text, "de", log)
    if "1038.7344.01" in result:
        print("✓ Stock number spacing: PASS")
        tests_passed += 1
    else:
        print(f"✗ Stock number spacing: FAIL (got '{result}')")
        tests_failed += 1

    # Test 3: German OCR fix
    test_text = "MeBtechnik ist wichtig"
    result = normalize_text(test_text, "de")
    if "Meßtechnik" in result:
        print("✓ German OCR fix: PASS")
        tests_passed += 1
    else:
        print(f"✗ German OCR fix: FAIL (got '{result}')")
        tests_failed += 1

    # Test 4: CID removal
    test_text = "Text (cid:1234) more text"
    result = normalize_text(test_text, "de")
    if "(cid:" not in result:
        print("✓ CID removal: PASS")
        tests_passed += 1
    else:
        print(f"✗ CID removal: FAIL (got '{result}')")
        tests_failed += 1

    # Test 4a: Fullwidth punctuation
    test_text = "Signal\uff0c dann 2\uff0e5 GHz"
    result = normalize_text(test_text, "de")
    if result == "Signal, dann 2.5 GHz":
        print("✓ Fullwidth punctuation: PASS")
        tests_passed += 1
    else:
        print(f"✗ Fullwidth punctuation: FAIL (got '{result}')")
        tests_failed += 1

    # Test 4b: Hz unit casing
    test_text = "1MHZ reference, 1KHZ offset, 2GHZ band"
    result = normalize_text(test_text, "en")
    if "1MHz" in result and "1kHz" in result and "2GHz" in result:
        print("✓ Hz unit case: PASS")
        tests_passed += 1
    else:
        print(f"✗ Hz unit case: FAIL (got '{result}')")
        tests_failed += 1

    # Test 4c: Micro-unit prefix
    test_text = "Wandlungszeit 9us, Pegel 100uV, Strom 2uA"
    result = normalize_text(test_text, "de")
    if "9 \u00b5s" in result and "100 \u00b5V" in result and "2 \u00b5A" in result:
        print("✓ Micro unit sign: PASS")
        tests_passed += 1
    else:
        print(f"✗ Micro unit sign: FAIL (got '{result}')")
        tests_failed += 1

    # Test 4c2: Cedilla-as-® recovery before R&S product codes; cedilla
    # followed by a single uppercase letter (e.g. French ``Ç``) is left
    # alone so legitimate usage isn't corrupted.
    test_text = "Three models: \u00b8SMP02, \u00b8SMP03 and the \u00b8FSEA family"
    result = normalize_text(test_text, "en")
    left_alone = "Fran\u00e7ais C\u00b8a"
    result_guard = normalize_text(left_alone, "en")
    ok = (
        "\u00aeSMP02" in result
        and "\u00aeSMP03" in result
        and "\u00aeFSEA" in result
        and "\u00b8" not in result
        and "C\u00b8a" in result_guard
    )
    if ok:
        print("✓ Cedilla-as-® recovery (guarded): PASS")
        tests_passed += 1
    else:
        print(f"✗ Cedilla-as-®: FAIL (got '{result}', guard='{result_guard}')")
        tests_failed += 1

    # Test 4d: Prufen umlaut restoration
    test_text = "7.4 Prufen und Abgleich; vorher gepruft"
    result = normalize_text(test_text, "de")
    if "Prüfen" in result and "geprüft" in result:
        print("✓ Prufen umlaut: PASS")
        tests_passed += 1
    else:
        print(f"✗ Prufen umlaut: FAIL (got '{result}')")
        tests_failed += 1

    # Test 4e: DE-strict umlaut — fires on language='de' only
    de_text = "Richtlinien fur Elektrogerate, konnen gemass Normen"
    result_de = normalize_text(de_text, "de")
    result_mix = normalize_text(de_text, "de+en")
    ok = (
        "für" in result_de
        and "können" in result_de
        and "gemäß" in result_de
        and "für" not in result_mix
    )
    if ok:
        print("✓ DE-strict umlaut (language-gated): PASS")
        tests_passed += 1
    else:
        print(f"✗ DE-strict umlaut: FAIL (de='{result_de}', mix='{result_mix}')")
        tests_failed += 1

    # Test 5: Designator normalization
    tests = [
        ("R117", "R117"),
        ("r117", "R117"),
        ("R117-A", "R117-A"),
        ("C42", "C42"),
        ("invalid", None),
    ]
    all_pass = True
    for input_val, exp in tests:
        dres = normalize_designator(input_val)
        if dres != exp:
            print(f"✗ Designator '{input_val}': expected '{exp}', got '{dres}'")
            all_pass = False
    if all_pass:
        print("✓ Designator normalization: PASS")
        tests_passed += 1
    else:
        tests_failed += 1

    # Test 6: Stock number normalization
    tests = [
        ("1038.7344.01", "1038.7344.01"),
        ("1038. 7344.01", "1038.7344.01"),
        ("1035.5005.02/03/04/22", "1035.5005.02/03/04/22"),
        ("invalid", None),
    ]
    all_pass = True
    for input_val, exp in tests:
        snres = normalize_stock_number(input_val)
        if snres != exp:
            print(f"✗ Stock number '{input_val}': expected '{exp}', got '{snres}'")
            all_pass = False
    if all_pass:
        print("✓ Stock number normalization: PASS")
        tests_passed += 1
    else:
        tests_failed += 1

    print(f"\n{tests_passed} passed, {tests_failed} failed")
    return tests_failed == 0


if __name__ == "__main__":
    import sys

    if "--test" in sys.argv:
        success = run_tests()
        sys.exit(0 if success else 1)
    else:
        print("normalize.py - Text normalization library")
        print("Usage: python normalize.py --test")
